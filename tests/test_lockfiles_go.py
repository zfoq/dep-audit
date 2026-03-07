"""Tests for the Go go.mod lockfile parser."""

from dep_audit.lockfiles_pkg.go import _parse_go_mod_content, normalize_go_module

_GOMOD_BASIC = """\
module github.com/example/myapp

go 1.21

require (
    github.com/pkg/errors v0.9.1
    github.com/sirupsen/logrus v1.9.3 // indirect
    golang.org/x/xerrors v0.0.0-20231012003756-9f7c6a7aa2e6 // indirect
)

require github.com/google/uuid v1.4.0
"""

_GOMOD_NO_INDIRECT = """\
module example.com/simple

go 1.20

require (
    github.com/hashicorp/go-multierror v1.1.1
    github.com/satori/go.uuid v1.2.0
)
"""

_GOMOD_EMPTY = """\
module example.com/empty

go 1.21
"""


def test_normalize_go_module():
    assert normalize_go_module("github.com/Pkg/Errors") == "github.com/pkg/errors"
    assert normalize_go_module("github.com/pkg/errors") == "github.com/pkg/errors"
    # Underscores are preserved (not converted to hyphens like Python/npm)
    assert normalize_go_module("github.com/foo/bar_baz") == "github.com/foo/bar_baz"


def test_parse_basic_direct_deps():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    names = {d.name for d in result.deps}
    assert "github.com/pkg/errors" in names
    assert "github.com/google/uuid" in names


def test_parse_indirect_deps_present():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    names = {d.name for d in result.deps}
    assert "github.com/sirupsen/logrus" in names
    assert "golang.org/x/xerrors" in names


def test_parse_direct_flag():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    by_name = {d.name: d for d in result.deps}
    assert by_name["github.com/pkg/errors"].is_direct is True
    assert by_name["github.com/google/uuid"].is_direct is True
    assert by_name["github.com/sirupsen/logrus"].is_direct is False
    assert by_name["golang.org/x/xerrors"].is_direct is False


def test_parse_root_module_excluded():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    names = {d.name for d in result.deps}
    assert "github.com/example/myapp" not in names


def test_parse_version_strips_v_prefix():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    by_name = {d.name: d for d in result.deps}
    assert by_name["github.com/pkg/errors"].version == "0.9.1"
    assert by_name["github.com/google/uuid"].version == "1.4.0"


def test_parse_pseudo_version():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    by_name = {d.name: d for d in result.deps}
    # pseudo-version: v0.0.0-20231012003756-9f7c6a7aa2e6
    assert by_name["golang.org/x/xerrors"].version.startswith("0.0.0-")


def test_parse_no_indirect_all_direct():
    result = _parse_go_mod_content(_GOMOD_NO_INDIRECT)
    by_name = {d.name: d for d in result.deps}
    assert by_name["github.com/hashicorp/go-multierror"].is_direct is True
    assert by_name["github.com/satori/go.uuid"].is_direct is True


def test_parse_empty_module():
    result = _parse_go_mod_content(_GOMOD_EMPTY)
    assert result.deps == []
    assert result.ecosystem == "go"


def test_parse_deduplication():
    gomod = """\
module example.com/app

go 1.21

require (
    github.com/pkg/errors v0.9.1
    github.com/pkg/errors v0.9.1
)
"""
    result = _parse_go_mod_content(gomod)
    names = [d.name for d in result.deps]
    assert names.count("github.com/pkg/errors") == 1


def test_parse_ecosystem_label():
    result = _parse_go_mod_content(_GOMOD_BASIC)
    assert result.ecosystem == "go"


def test_parse_source_label():
    result = _parse_go_mod_content(_GOMOD_BASIC, source_label="go.mod (remote)")
    assert result.source_file == "go.mod (remote)"
