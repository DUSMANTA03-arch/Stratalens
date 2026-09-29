// npm install, then npm run test:database. Executes the actual migration in PostgreSQL/WASM.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
const { PGlite } = await import(
  process.env.PGLITE_MODULE || "@electric-sql/pglite"
);
const db = new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
create schema auth; create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;
create schema storage; create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);`);
await db.exec(
  await fs.readFile(
    new URL("../migrations/001_workspace.sql", import.meta.url),
    "utf8",
  ),
);
await db.exec(
  await fs.readFile(
    new URL("../migrations/002_reliability.sql", import.meta.url),
    "utf8",
  ),
);
const owner = "00000000-0000-0000-0000-000000000001",
  other = "00000000-0000-0000-0000-000000000002";
const job = "10000000-0000-0000-0000-000000000001",
  job2 = "10000000-0000-0000-0000-000000000002";
const token = "20000000-0000-0000-0000-000000000001",
  token2 = "20000000-0000-0000-0000-000000000002";
const document = "30000000-0000-0000-0000-000000000001",
  observation = "40000000-0000-0000-0000-000000000001";
await db.query("insert into auth.users values ($1),($2)", [owner, other]);
await db.query("insert into public.workspace_owners(user_id) values ($1)", [
  owner,
]);
await db.query(
  "insert into public.workspace_jobs(id,owner_id,kind) values ($1,$3,'research'),($2,$3,'ingest')",
  [job, job2, owner],
);
async function rpc(name, args) {
  return (
    await db.query(
      `select public.${name}(${args.map((_, i) => "$" + (i + 1)).join(",")}) as result`,
      args,
    )
  ).rows[0].result;
}
assert.equal((await rpc("claim_workspace_job", [owner, job, token])).id, job);
assert.equal(
  await rpc("claim_workspace_job", [owner, job2, token2]),
  null,
  "one active job per owner",
);
assert.equal(
  await rpc("claim_workspace_job", [other, job2, token2]),
  null,
  "other user cannot claim",
);
assert.equal(
  await rpc("reserve_workspace_call", [owner, job, token, "model"]),
  true,
);
assert.equal(
  await rpc("reserve_workspace_call", [owner, job, token2, "model"]),
  false,
  "wrong fencing token",
);
await db.query(
  "update public.workspace_usage set model_calls=100 where owner_id=$1",
  [owner],
);
assert.equal(
  await rpc("reserve_workspace_call", [owner, job, token, "model"]),
  false,
  "daily budget blocks before dispatch",
);
await db.query(
  "update public.workspace_usage set model_calls=1 where owner_id=$1",
  [owner],
);
await db.query("update public.workspace_jobs set model_calls=20 where id=$1", [
  job,
]);
assert.equal(
  await rpc("reserve_workspace_call", [owner, job, token, "model"]),
  false,
  "job budget blocks before dispatch",
);
await db.query("update public.workspace_jobs set model_calls=1 where id=$1", [
  job,
]);
const doc = {
  id: document,
  kind: "document",
  data: { title: "Report", size: 100, status: "indexing" },
};
const page = {
  document_id: document,
  page: 25,
  text: "Revenue from operations grew to 1250 crore.",
  tables: [],
  truncated: false,
};
assert.equal(
  await rpc("commit_workspace_job", [
    owner,
    job,
    token2,
    {},
    "queued",
    null,
    null,
    [doc],
    [page],
  ]),
  false,
);
assert.equal(
  await rpc("commit_workspace_job", [
    owner,
    job,
    token,
    { phase: "writer" },
    "queued",
    null,
    null,
    [doc],
    [page],
  ]),
  true,
);
assert.equal(
  (
    await db.query("select * from public.search_workspace_pages($1,$2,$3)", [
      owner,
      [document],
      "revenue",
    ])
  ).rows[0].page,
  25,
);
assert.equal(
  (
    await db.query("select * from public.search_workspace_pages($1,$2,$3)", [
      other,
      [document],
      "revenue",
    ])
  ).rows.length,
  0,
);
await rpc("claim_workspace_job", [owner, job, token]);
await db.query(
  "update public.workspace_jobs set lease_until=now()-interval '1 second' where id=$1",
  [job],
);
assert.equal(
  (await rpc("claim_workspace_job", [owner, job, token2])).lease_token,
  token2,
);
assert.equal(
  await rpc("commit_workspace_job", [
    owner,
    job,
    token,
    {},
    "completed",
    null,
    null,
    [],
    [],
  ]),
  false,
  "expired worker cannot write",
);
await rpc("cancel_workspace_job", [owner, job]);
assert.equal(
  await rpc("commit_workspace_job", [
    owner,
    job,
    token2,
    {},
    "completed",
    null,
    null,
    [],
    [],
  ]),
  false,
  "cancelled worker cannot write",
);
assert.equal(
  await rpc("allocate_workspace_document", [
    owner,
    "30000000-0000-0000-0000-000000000002",
    { size: 800000000 },
  ]),
  false,
  "storage reservation is bounded",
);
await db.query(
  "insert into public.workspace_records(id,owner_id,kind,data) values($1,$2,'observation',$3)",
  [
    observation,
    owner,
    {
      document_id: document,
      value: 1250,
      original_value: 1250,
      corrections: [],
    },
  ],
);
const version = (
  await db.query(
    "select updated_at::text from public.workspace_records where id=$1",
    [observation],
  )
).rows[0].updated_at;
assert.equal(
  await rpc("correct_workspace_observation", [
    owner,
    observation,
    1500,
    "Checked against source",
    "2000-01-01",
  ]),
  null,
);
const corrected = await rpc("correct_workspace_observation", [
  owner,
  observation,
  1500,
  "Checked against source",
  version,
]);
assert.equal(corrected.data.original_value, 1250);
assert.equal(corrected.data.corrections.length, 1);
assert.equal(corrected.data.review_status, "unreviewed");
assert.equal(corrected.data.observation_version, 2);
assert.equal(
  await rpc("review_workspace_observation", [
    other,
    observation,
    "reviewed",
    "Verified",
    corrected.updated_at,
  ]),
  null,
);
const reviewed = await rpc("review_workspace_observation", [
  owner,
  observation,
  "reviewed",
  "Verified source",
  corrected.updated_at,
]);
assert.equal(reviewed.data.review.version, 2);
assert.equal(
  await rpc("review_workspace_observation", [
    owner,
    observation,
    "excluded",
    "Another decision",
    corrected.updated_at,
  ]),
  null,
  "stale review rejected",
);
const correctedAgain = await rpc("correct_workspace_observation", [
  owner,
  observation,
  1600,
  "Corrected against source page",
  reviewed.updated_at,
]);
assert.equal(correctedAgain.data.review_status, "unreviewed");
assert.equal(correctedAgain.data.review, undefined);
assert.equal(correctedAgain.data.review_history.length, 1);
assert.equal(correctedAgain.data.original_extraction.value, 1250);
assert.equal(correctedAgain.data.corrections.length, 2);
const note = "50000000-0000-0000-0000-000000000001";
await db.query(
  "insert into public.workspace_records(id,owner_id,kind,data) values($1,$2,'note',$3)",
  [note, owner, { target_id: observation, text: "My note" }],
);
const noteVersion = (
  await db.query(
    "select updated_at::text from public.workspace_records where id=$1",
    [note],
  )
).rows[0].updated_at;
assert.equal(
  await rpc("patch_workspace_record", [
    other,
    "note",
    note,
    noteVersion,
    { text: "Foreign edit" },
    false,
  ]),
  null,
);
const edited = await rpc("patch_workspace_record", [
  owner,
  "note",
  note,
  noteVersion,
  { text: "Edited note" },
  false,
]);
assert.equal(edited.data.text, "Edited note");
assert.equal(
  await rpc("patch_workspace_record", [
    owner,
    "note",
    note,
    noteVersion,
    {},
    true,
  ]),
  null,
);
assert.deepEqual(
  await rpc("patch_workspace_record", [
    owner,
    "note",
    note,
    edited.updated_at,
    {},
    true,
  ]),
  { ok: true },
);
await db.exec("set role authenticated");
await db.query("select set_config('request.jwt.claim.sub',$1,false)", [other]);
assert.equal(
  (await db.query("select * from public.workspace_records")).rows.length,
  0,
  "RLS hides owner data",
);
await db.query("select set_config('request.jwt.claim.sub',$1,false)", [owner]);
assert.equal(
  (await db.query("select * from public.workspace_records")).rows.length,
  2,
);
await assert.rejects(
  db.query("update public.workspace_records set data='{}'"),
  /permission denied/,
);
await assert.rejects(
  rpc("claim_workspace_job", [owner, job, token]),
  /permission denied/,
);
await assert.rejects(
  rpc("review_workspace_observation", [
    owner,
    observation,
    "reviewed",
    "Source checked",
    correctedAgain.updated_at,
  ]),
  /permission denied/,
);
await assert.rejects(
  rpc("patch_workspace_record", [
    owner,
    "document",
    document,
    version,
    {},
    false,
  ]),
  /permission denied/,
);
await db.exec("reset role");
await rpc("delete_workspace_document", [owner, document]);
assert.equal(
  (await db.query("select * from public.document_pages")).rows.length,
  0,
  "deletion cascades indexed pages",
);
assert.equal(
  (
    await db.query(
      "select * from public.workspace_records where kind='observation'",
    )
  ).rows.length,
  0,
);
await db.close();
console.log(
  "PostgreSQL migration, RLS, leases, fencing, cancellation, quotas, FTS, audit, and deletion checks passed.",
);
