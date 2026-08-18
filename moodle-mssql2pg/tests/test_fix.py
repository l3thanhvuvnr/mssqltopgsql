from moodle_mssql2pg.fix import (
    drop_fk_statements,
    fix_sequence_statement,
    trim_char_statements,
    vacuum_analyze_statement,
)


def test_drop_fk_statements():
    stmts = drop_fk_statements("public", [("mdl_user", "fk_user_ctx")])
    assert stmts == [
        'ALTER TABLE "public"."mdl_user" DROP CONSTRAINT IF EXISTS "fk_user_ctx";'
    ]


def test_trim_char_statements_one_per_column():
    stmts = trim_char_statements("public", {"mdl_user": ["country", "lang"]})
    assert stmts == [
        'UPDATE "public"."mdl_user" SET "country" = rtrim("country") '
        'WHERE "country" <> rtrim("country");',
        'UPDATE "public"."mdl_user" SET "lang" = rtrim("lang") '
        'WHERE "lang" <> rtrim("lang");',
    ]


def test_fix_sequence_statement_mentions_setval_and_table():
    stmt = fix_sequence_statement("public", "mdl_user")
    assert "setval" in stmt
    assert "mdl_user" in stmt
    assert "pg_get_serial_sequence" in stmt


def test_vacuum_analyze():
    assert vacuum_analyze_statement() == "VACUUM ANALYZE;"
