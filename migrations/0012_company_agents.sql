-- Агенты компании = именованные наборы навыков (ссылаются на company_skills по имени).
-- Навык остаётся атомарным и может входить в несколько агентов.
create table if not exists company_agents (
    slug        text primary key,
    title       text        not null default '',
    description text        not null default '',
    department  text        not null default '',
    skills      jsonb       not null default '[]'::jsonb,  -- список имён навыков
    updated_by  text        not null default '',
    updated_at  timestamptz not null default now()
);
