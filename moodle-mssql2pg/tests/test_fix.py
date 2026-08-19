from moodle_mssql2pg.fix import (
    drop_fk_statements,
    fix_sequence_statement,
    trim_char_statements,
    vacuum_analyze_statement,
    missing_index_statements,
    restore_typemod_statements,
    safe_index_name,
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


def test_restore_typemod_covers_varchar_and_numeric():
    # pgloader bo typemod -> "text" gay textconditionsnotallowed, "numeric" khong
    # precision gay 'size is (-1,65531), expected (10,5)'.
    stmts = restore_typemod_statements(
        "public",
        {
            "mdl_config_plugins": [["name", "varchar(100)"]],
            "mdl_grade_grades": [["finalgrade", "numeric(10,5)"]],
        },
    )
    assert stmts == [
        'ALTER TABLE "public"."mdl_config_plugins" '
        'ALTER COLUMN "name" TYPE varchar(100);',
        'ALTER TABLE "public"."mdl_grade_grades" '
        'ALTER COLUMN "finalgrade" TYPE numeric(10,5);',
    ]


def test_restore_typemod_empty_when_nothing_to_fix():
    assert restore_typemod_statements("public", {}) == []


def test_safe_index_name_keeps_short_names_unchanged():
    assert safe_index_name("mdl_user_use_ix") == "mdl_user_use_ix"


def test_safe_index_name_shortens_and_stays_unique():
    a = "mdl_enrol_lti_lti2_share_key$mdl_enroltilti2sharkey_sha_uix" + "x" * 40
    b = "mdl_enrol_lti_lti2_share_key$mdl_enroltilti2sharkey_res_uix" + "x" * 40
    na, nb = safe_index_name(a), safe_index_name(b)
    assert len(na) <= 63 and len(nb) <= 63
    assert na != nb  # cung tien to nhung hau to bam khac nhau
    assert "$" not in na


def test_missing_index_statements_skips_ones_already_there():
    source = [
        ["mdl_enrol_lti_lti2_share_key", "sk_res_uix", 1, "resourcelinkid"],
        ["mdl_enrol_lti_lti2_share_key", "sk_sha_uix", 1, "sharekey"],
    ]
    existing = {("mdl_enrol_lti_lti2_share_key", 1, "resourcelinkid")}
    stmts = missing_index_statements("public", source, existing)
    assert stmts == [
        'CREATE UNIQUE INDEX IF NOT EXISTS "sk_sha_uix" '
        'ON "public"."mdl_enrol_lti_lti2_share_key" ("sharekey");'
    ]


def test_missing_index_statements_handles_multi_column_and_nonunique():
    stmts = missing_index_statements(
        "public", [["mdl_log", "log_cmu_ix", 0, "course,module,user"]], set()
    )
    assert stmts == [
        'CREATE INDEX IF NOT EXISTS "log_cmu_ix" '
        'ON "public"."mdl_log" ("course", "module", "user");'
    ]
