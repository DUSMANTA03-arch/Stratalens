-- Run once in the Supabase SQL editor. Then insert the Auth owner's UUID below.
create table if not exists public.workspace_owners (
  user_id uuid primary key references auth.users(id) on delete cascade,
  singleton boolean not null default true unique check (singleton)
);
alter table public.workspace_owners enable row level security;
create policy owner_identity on public.workspace_owners for select to authenticated using (user_id = auth.uid());

create table public.workspace_records (
  id uuid primary key,
  owner_id uuid not null references public.workspace_owners(user_id),
  kind text not null check (kind in ('company','document','observation','brief','conversation','discovery','asset')),
  data jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index records_owner_kind on public.workspace_records(owner_id,kind);
create index records_document on public.workspace_records((data->>'document_id'));
create unique index document_checksum on public.workspace_records(owner_id,(data->>'checksum'))
  where kind='document' and data->>'checksum' is not null;
alter table public.workspace_records enable row level security;
create policy owner_records on public.workspace_records for select to authenticated using (owner_id=auth.uid());

create table public.document_pages (
  document_id uuid not null references public.workspace_records(id) on delete cascade,
  owner_id uuid not null references public.workspace_owners(user_id),
  page integer not null check (page between 1 and 600),
  text text not null,
  tables jsonb not null default '[]',
  truncated boolean not null default false,
  search tsvector generated always as (to_tsvector('english',text)) stored,
  primary key(document_id,page)
);
create index pages_search on public.document_pages using gin(search);
alter table public.document_pages enable row level security;
create policy owner_pages on public.document_pages for select to authenticated using (owner_id=auth.uid());

create table public.workspace_jobs (
  id uuid primary key,
  owner_id uuid not null references public.workspace_owners(user_id),
  kind text not null check(kind in ('ingest','research','chat','discover')),
  status text not null default 'queued' check(status in ('queued','running','paused','completed','failed','cancelled')),
  state jsonb not null default '{}',
  result jsonb,
  error text,
  lease_token uuid,
  lease_until timestamptz,
  model_calls integer not null default 0,
  search_calls integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index jobs_owner on public.workspace_jobs(owner_id,created_at desc);
alter table public.workspace_jobs enable row level security;
create policy owner_jobs on public.workspace_jobs for select to authenticated using(owner_id=auth.uid());

create table public.workspace_usage (
  owner_id uuid not null references public.workspace_owners(user_id),
  day date not null default current_date,
  model_calls integer not null default 0,
  search_calls integer not null default 0,
  primary key(owner_id,day)
);
alter table public.workspace_usage enable row level security;
create policy owner_usage on public.workspace_usage for select to authenticated using(owner_id=auth.uid());

-- Only the server can mutate workspace state; browser sessions have read-only RLS.
revoke all on public.workspace_records,public.document_pages,public.workspace_jobs,public.workspace_usage,public.workspace_owners from anon;
revoke insert,update,delete on public.workspace_records,public.document_pages,public.workspace_jobs,public.workspace_usage,public.workspace_owners from authenticated;
grant select on public.workspace_records,public.document_pages,public.workspace_jobs,public.workspace_usage,public.workspace_owners to authenticated;

create function public.claim_workspace_job(p_owner uuid,p_job uuid,p_token uuid)
returns jsonb language plpgsql set search_path='' as $$
declare j public.workspace_jobs;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
  if exists(select 1 from public.workspace_jobs where owner_id=p_owner and lease_until>now()) then return null; end if;
  update public.workspace_jobs set status='running',lease_token=p_token,lease_until=now()+interval '240 seconds',updated_at=now(),error=null
  where id=p_job and owner_id=p_owner and status in ('queued','running','paused') returning * into j;
  if j.id is null then return null; end if;
  return to_jsonb(j);
end $$;

create function public.commit_workspace_job(p_owner uuid,p_job uuid,p_token uuid,p_state jsonb,p_status text,
 p_result jsonb default null,p_error text default null,p_records jsonb default '[]',p_pages jsonb default '[]')
returns boolean language plpgsql set search_path='' as $$
declare item jsonb;
begin
  perform 1 from public.workspace_jobs where id=p_job and owner_id=p_owner and lease_token=p_token and lease_until>now() and status='running' for update;
  if not found then return false; end if;
  if pg_total_relation_size('public.document_pages')+pg_total_relation_size('public.workspace_records')+pg_total_relation_size('public.workspace_jobs')>350000000 then
    raise exception 'Workspace database storage limit reached; delete unused documents.';
  end if;
  for item in select * from jsonb_array_elements(p_records) loop
    insert into public.workspace_records(id,owner_id,kind,data) values((item->>'id')::uuid,p_owner,item->>'kind',item->'data')
    on conflict(id) do update set data=excluded.data,updated_at=now() where public.workspace_records.owner_id=p_owner;
  end loop;
  for item in select * from jsonb_array_elements(p_pages) loop
    insert into public.document_pages(document_id,owner_id,page,text,tables,truncated)
    values((item->>'document_id')::uuid,p_owner,(item->>'page')::int,item->>'text',coalesce(item->'tables','[]'),coalesce((item->>'truncated')::boolean,false))
    on conflict(document_id,page) do update set text=excluded.text,tables=excluded.tables,truncated=excluded.truncated;
  end loop;
  update public.workspace_jobs set state=p_state,status=p_status,result=p_result,error=p_error,lease_token=null,lease_until=null,updated_at=now() where id=p_job;
  return true;
end $$;

create function public.reserve_workspace_call(p_owner uuid,p_job uuid,p_token uuid,p_kind text)
returns boolean language plpgsql set search_path='' as $$
declare j public.workspace_jobs; u public.workspace_usage; cap integer;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
  select * into j from public.workspace_jobs where id=p_job and owner_id=p_owner and lease_token=p_token and lease_until>now() and status='running' for update;
  if j.id is null or p_kind not in ('model','search') then return false; end if;
  insert into public.workspace_usage(owner_id) values(p_owner) on conflict do nothing;
  select * into u from public.workspace_usage where owner_id=p_owner and day=current_date for update;
  cap := case when j.kind='ingest' then 80 when j.kind='research' then 20 else 4 end;
  if p_kind='model' then
    if j.model_calls>=cap or u.model_calls>=100 then return false; end if;
    update public.workspace_jobs set model_calls=model_calls+1 where id=p_job;
    update public.workspace_usage set model_calls=model_calls+1 where owner_id=p_owner and day=current_date;
  else
    if j.search_calls>=6 or u.search_calls>=20 then return false; end if;
    update public.workspace_jobs set search_calls=search_calls+1 where id=p_job;
    update public.workspace_usage set search_calls=search_calls+1 where owner_id=p_owner and day=current_date;
  end if;
  return true;
end $$;

create function public.search_workspace_pages(p_owner uuid,p_documents uuid[],p_query text)
returns setof public.document_pages language sql stable set search_path='' as $$
 select p.* from public.document_pages p join (
   select document_id,page,ts_rank_cd(search,websearch_to_tsquery('english',p_query)) as score,
   row_number() over(partition by document_id order by ts_rank_cd(search,websearch_to_tsquery('english',p_query)) desc,page) as position
   from public.document_pages where owner_id=p_owner and document_id=any(p_documents)
   and search @@ websearch_to_tsquery('english',p_query)
 ) ranked using(document_id,page)
 order by ranked.position,ranked.score desc,p.document_id,p.page limit 12
$$;

create function public.cancel_workspace_job(p_owner uuid,p_job uuid)
returns void language sql set search_path='' as $$
 update public.workspace_jobs set status='cancelled',lease_token=null,lease_until=null,updated_at=now()
 where id=p_job and owner_id=p_owner and status not in ('completed','cancelled')
$$;

create function public.delete_workspace_document(p_owner uuid,p_document uuid)
returns boolean language plpgsql set search_path='' as $$
begin
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 if exists(select 1 from public.workspace_jobs where owner_id=p_owner and lease_until>now()) then return false; end if;
 update public.workspace_jobs set status='cancelled',lease_token=null,lease_until=null
 where owner_id=p_owner and status in ('queued','paused','running') and
 (state->>'document_id'=p_document::text or state->'document_ids' ? p_document::text);
 delete from public.workspace_records where owner_id=p_owner and kind='observation' and data->>'document_id'=p_document::text;
 delete from public.document_pages where owner_id=p_owner and document_id=p_document;
 update public.workspace_records set data=data||'{"status":"deleting"}'::jsonb,updated_at=now()
 where owner_id=p_owner and id=p_document and kind='document';
 return true;
end $$;

-- Signed uploads are issued by the backend. No public bucket/list/upload policy.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('reports','reports',false,40000000,array['application/pdf','image/jpeg'])
on conflict(id) do update set public=false,file_size_limit=40000000,allowed_mime_types=excluded.allowed_mime_types;

revoke execute on function public.claim_workspace_job(uuid,uuid,uuid),public.commit_workspace_job(uuid,uuid,uuid,jsonb,text,jsonb,text,jsonb,jsonb),public.reserve_workspace_call(uuid,uuid,uuid,text),public.search_workspace_pages(uuid,uuid[],text),public.cancel_workspace_job(uuid,uuid),public.delete_workspace_document(uuid,uuid) from public,anon,authenticated;
grant execute on function public.claim_workspace_job(uuid,uuid,uuid),public.commit_workspace_job(uuid,uuid,uuid,jsonb,text,jsonb,text,jsonb,jsonb),public.reserve_workspace_call(uuid,uuid,uuid,text),public.search_workspace_pages(uuid,uuid[],text),public.cancel_workspace_job(uuid,uuid),public.delete_workspace_document(uuid,uuid) to service_role;
-- After creating the owner in Authentication > Users:
-- insert into public.workspace_owners(user_id) values ('YOUR-AUTH-USER-UUID');

create function public.allocate_workspace_document(p_owner uuid,p_document uuid,p_data jsonb)
returns boolean language plpgsql set search_path='' as $$
begin
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 if (select coalesce(sum((data->>'size')::bigint),0) from public.workspace_records where owner_id=p_owner and kind in ('document','asset'))+(p_data->>'size')::bigint>800000000 then return false; end if;
 insert into public.workspace_records(id,owner_id,kind,data) values(p_document,p_owner,'document',p_data);
 return true;
end $$;

create function public.correct_workspace_observation(p_owner uuid,p_observation uuid,p_value double precision,p_reason text,p_expected text)
returns jsonb language plpgsql set search_path='' as $$
declare r public.workspace_records; entry jsonb;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 if exists(select 1 from public.workspace_jobs where owner_id=p_owner and lease_until>now()) then return null; end if;
 select * into r from public.workspace_records where owner_id=p_owner and id=p_observation and kind='observation' for update;
 if r.id is null or r.updated_at<>p_expected::timestamptz then return null; end if;
 entry:=jsonb_build_object('previous_value',r.data->'value','value',p_value,'reason',p_reason,'at',now(),'owner_id',p_owner);
 update public.workspace_records set data=data||jsonb_build_object('value',p_value,'review_status','manually_corrected',
 'corrections',coalesce(data->'corrections','[]'::jsonb)||jsonb_build_array(entry)),updated_at=now() where id=p_observation returning * into r;
 return to_jsonb(r);
end $$;
revoke execute on function public.allocate_workspace_document(uuid,uuid,jsonb),public.correct_workspace_observation(uuid,uuid,double precision,text,text) from public,anon,authenticated;
grant execute on function public.allocate_workspace_document(uuid,uuid,jsonb),public.correct_workspace_observation(uuid,uuid,double precision,text,text) to service_role;

create function public.allocate_workspace_asset(p_owner uuid,p_asset uuid,p_data jsonb)
returns boolean language plpgsql set search_path='' as $$
begin
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 if exists(select 1 from public.workspace_records where id=p_asset and owner_id=p_owner and kind='asset') then return true; end if;
 if (select coalesce(sum((data->>'size')::bigint),0) from public.workspace_records where owner_id=p_owner and kind in ('document','asset'))+(p_data->>'size')::bigint>800000000 then return false; end if;
 insert into public.workspace_records(id,owner_id,kind,data) values(p_asset,p_owner,'asset',p_data);
 return true;
end $$;
revoke execute on function public.allocate_workspace_asset(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.allocate_workspace_asset(uuid,uuid,jsonb) to service_role;
grant all on public.workspace_records,public.workspace_jobs,public.workspace_usage,public.workspace_owners,public.document_pages to service_role;
