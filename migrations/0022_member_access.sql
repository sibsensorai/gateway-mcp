-- Допуск участников к ядру: новый человек с почтой компании ждёт одобрения администратора.
create table member_access (
    member_key text primary key,
    subject text not null default '',
    email text not null default '',
    login text not null default '',
    status text not null check (status in ('pending', 'approved', 'rejected')),
    approval_id text not null default '',
    requested_at timestamptz not null default now(),
    decided_by text not null default '',
    decided_at timestamptz,
    note text not null default ''
);

create index member_access_status_idx on member_access (status, requested_at desc);

-- Все, кто уже входил в ядро до этой версии, допущены автоматически.
insert into member_access (member_key, subject, email, login, status, decided_by, decided_at, note)
select distinct on (lower(coalesce(nullif(email, ''), actor_subject)))
    lower(coalesce(nullif(email, ''), actor_subject)),
    actor_subject, email, login, 'approved', 'migration:0022', now(), 'вход до включения одобрения'
from user_oauth_tokens
where provider = 'yandex' and actor_subject <> ''
order by lower(coalesce(nullif(email, ''), actor_subject)), updated_at desc
on conflict (member_key) do nothing;
