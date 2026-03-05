"""Tests for JavaScript/TypeScript import scanning."""

from __future__ import annotations

from dep_audit.usage import scan_javascript_imports


def _write_js(tmp_path, filename, content):
    """Write a JS file and return the path."""
    f = tmp_path / filename
    f.write_text(content)
    return f


def test_scan_require(tmp_path):
    _write_js(tmp_path, "index.js", 'const express = require("express");\n')
    result = scan_javascript_imports(tmp_path, {"express"})
    assert result["express"].import_count == 1
    assert result["express"].file_count == 1


def test_scan_require_single_quotes(tmp_path):
    _write_js(tmp_path, "app.js", "const fetch = require('node-fetch');\n")
    result = scan_javascript_imports(tmp_path, {"node-fetch"})
    assert result["node-fetch"].import_count == 1


def test_scan_esm_import(tmp_path):
    _write_js(tmp_path, "index.mjs", 'import express from "express";\n')
    result = scan_javascript_imports(tmp_path, {"express"})
    assert result["express"].import_count == 1


def test_scan_esm_named_import(tmp_path):
    _write_js(tmp_path, "index.js", 'import { Router } from "express";\n')
    result = scan_javascript_imports(tmp_path, {"express"})
    assert result["express"].import_count == 1


def test_scan_side_effect_import(tmp_path):
    _write_js(tmp_path, "setup.js", 'import "dotenv/config";\n')
    result = scan_javascript_imports(tmp_path, {"dotenv"})
    assert result["dotenv"].import_count == 1


def test_scan_dynamic_import(tmp_path):
    _write_js(tmp_path, "lazy.js", 'const mod = await import("lodash");\n')
    result = scan_javascript_imports(tmp_path, {"lodash"})
    assert result["lodash"].import_count == 1


def test_scan_reexport(tmp_path):
    _write_js(tmp_path, "index.js", 'export { default } from "express";\n')
    result = scan_javascript_imports(tmp_path, {"express"})
    assert result["express"].import_count == 1


def test_scan_scoped_package(tmp_path):
    _write_js(tmp_path, "app.ts", 'import { Injectable } from "@nestjs/common";\n')
    result = scan_javascript_imports(tmp_path, {"@nestjs/common"})
    assert result["@nestjs/common"].import_count == 1


def test_scan_ignores_relative_imports(tmp_path):
    _write_js(tmp_path, "foo.js", 'import bar from "./bar";\n')
    result = scan_javascript_imports(tmp_path, {"bar"})
    assert result["bar"].import_count == 0


def test_scan_ignores_node_modules(tmp_path):
    nm = tmp_path / "node_modules" / "express"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text('const http = require("http");\n')
    _write_js(tmp_path, "app.js", 'const express = require("express");\n')
    result = scan_javascript_imports(tmp_path, {"http", "express"})
    assert result["http"].import_count == 0  # inside node_modules — excluded
    assert result["express"].import_count == 1


def test_scan_typescript_files(tmp_path):
    _write_js(tmp_path, "app.tsx", 'import React from "react";\n')
    result = scan_javascript_imports(tmp_path, {"react"})
    assert result["react"].import_count == 1
    assert result["react"].files[0].path == "app.tsx"


def test_scan_multiple_imports_same_file(tmp_path):
    _write_js(tmp_path, "app.js", (
        'const express = require("express");\n'
        'const { Router } = require("express");\n'
    ))
    result = scan_javascript_imports(tmp_path, {"express"})
    assert result["express"].import_count == 2
    assert result["express"].file_count == 1


def test_scan_unmatched_package(tmp_path):
    _write_js(tmp_path, "app.js", 'import x from "react";\n')
    result = scan_javascript_imports(tmp_path, {"express"})
    assert result["express"].import_count == 0


def test_scan_subpath_import(tmp_path):
    """import from 'lodash/map' should match package 'lodash'."""
    _write_js(tmp_path, "app.js", 'import map from "lodash/map";\n')
    result = scan_javascript_imports(tmp_path, {"lodash"})
    assert result["lodash"].import_count == 1
