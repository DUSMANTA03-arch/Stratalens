-- Apply once after 001, after backing up workspace records and jobs.
begin;
alter table public.workspace_records drop constraint workspace_records_kind_check;
alter table public.workspace_records add constraint workspace_records_kind_check
 check(kind in ('company','document','observation','brief','conversation','discovery','asset','note'));

create function public.version_workspace_observation() returns trigger language plpgsql set search_path='' as $$
begin
 if new.kind='observation' then
  if tg_op='INSERT' then
   new.data := (new.data - 'review') || jsonb_build_object('observation_version',1,'review_status','unreviewed');
  elsif (new.data - array['review','review_status','review_history','observation_version']) is distinct from
        (old.data - array['review','review_status','review_history','observation_version']) then
   new.data := (new.data - 'review') || jsonb_build_object(
     'observation_version',coalesce((old.data->>'observation_version')::int,1)+1,
     'review_status','unreviewed', 'review_history',coalesce(old.data->'review_history','[]'::jsonb),
     'original_value',coalesce(old.data->'original_value',old.data->'value'),
     'original_extraction',coalesce(old.data->'original_extraction',old.data),
     'corrections',case when jsonb_array_length(coalesce(new.data->'corrections','[]'::jsonb)) >= jsonb_array_length(coalesce(old.data->'corrections','[]'::jsonb)) then coalesce(new.data->'corrections','[]'::jsonb) else old.data->'corrections' end);
  end if;
 end if;
 return new;
end $$;
create trigger observation_version before insert or update on public.workspace_records
 for each row execute function public.version_workspace_observation();

create function public.review_workspace_observation(p_owner uuid,p_observation uuid,p_status text,p_reason text,p_expected text)
returns jsonb language plpgsql set search_path='' as $$
declare r public.workspace_records; entry jsonb;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 if p_status not in ('reviewed','unreviewed','excluded') then return null; end if;
 if p_status='excluded' and length(trim(p_reason))<10 then return null; end if;
 if exists(select 1 from public.workspace_jobs where owner_id=p_owner and lease_until>now()) then return null; end if;
 select * into r from public.workspace_records where owner_id=p_owner and id=p_observation and kind='observation' for update;
 if r.id is null or r.updated_at<>p_expected::timestamptz then return null; end if;
 entry:=jsonb_build_object('status',p_status,'reason',p_reason,'version',coalesce((r.data->>'observation_version')::int,1),'at',clock_timestamp(),'owner_id',p_owner);
 update public.workspace_records set data=data||jsonb_build_object('review',entry,'review_status',p_status,
 'review_history',coalesce(data->'review_history','[]'::jsonb)||jsonb_build_array(entry)),updated_at=clock_timestamp()
 where id=p_observation returning * into r;
 return to_jsonb(r);
end $$;

create function public.patch_workspace_record(p_owner uuid,p_kind text,p_record uuid,p_expected text,p_patch jsonb,p_delete boolean default false)
returns jsonb language plpgsql set search_path='' as $$
declare r public.workspace_records;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 if p_kind not in ('company','document','note') or (p_delete and p_kind<>'note') then return null; end if;
 if p_kind<>'note' and exists(select 1 from public.workspace_jobs where owner_id=p_owner and lease_until>now()) then return null; end if;
 select * into r from public.workspace_records where owner_id=p_owner and id=p_record and kind=p_kind for update;
 if r.id is null or r.updated_at<>p_expected::timestamptz then return null; end if;
 if p_delete then
  delete from public.workspace_records where id=p_record;
  return jsonb_build_object('ok',true);
 end if;
 update public.workspace_records set data=data||p_patch,updated_at=clock_timestamp() where id=p_record returning * into r;
 return to_jsonb(r);
end $$;
revoke execute on function public.version_workspace_observation(),public.review_workspace_observation(uuid,uuid,text,text,text),public.patch_workspace_record(uuid,text,uuid,text,jsonb,boolean) from public,anon,authenticated;
grant execute on function public.review_workspace_observation(uuid,uuid,text,text,text),public.patch_workspace_record(uuid,text,uuid,text,jsonb,boolean) to service_role;
create function public.workspace_reliability_ready(p_owner uuid) returns boolean language sql stable set search_path='' as $$
 select exists(select 1 from public.workspace_owners where user_id=p_owner)
$$;
revoke execute on function public.workspace_reliability_ready(uuid) from public,anon,authenticated;
grant execute on function public.workspace_reliability_ready(uuid) to service_role;
commit;
