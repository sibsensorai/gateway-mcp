-- Навыки компании хранятся в ядре (обновляются на лету, без пересборки образа).
create table if not exists company_skills (
    name        text primary key,
    pack        text        not null default '',
    department  text        not null default '',
    title       text        not null default '',
    description text        not null default '',
    content     text        not null default '',
    updated_by  text        not null default '',
    updated_at  timestamptz not null default now()
);
