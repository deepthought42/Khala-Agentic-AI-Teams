"""Unit tests for command_runner repair helpers and scaffold."""

from pathlib import Path
from unittest.mock import patch

import pytest

from shared.command_runner import (
    CommandResult,
    _ensure_angular_material_in_package_json,
    _ensure_material_theme_in_styles,
    _ensure_provide_animations_in_config,
    ensure_frontend_dependencies_installed,
    ensure_frontend_project_initialized,
)


def test_ensure_angular_material_in_package_json_adds_missing_deps(tmp_path: Path) -> None:
    """When package.json lacks @angular/material and @angular/cdk, they are added."""
    pkg = tmp_path / "package.json"
    pkg.write_text('{"dependencies": {"@angular/core": "^18.0.0"}}', encoding="utf-8")
    _ensure_angular_material_in_package_json(tmp_path)
    data = __import__("json").loads(pkg.read_text(encoding="utf-8"))
    assert "@angular/material" in data["dependencies"]
    assert "@angular/cdk" in data["dependencies"]


def test_ensure_angular_material_in_package_json_noop_when_present(tmp_path: Path) -> None:
    """When package.json already has Material, it is unchanged."""
    orig = '{"dependencies": {"@angular/material": "^18.0.0", "@angular/cdk": "^18.0.0"}}'
    pkg = tmp_path / "package.json"
    pkg.write_text(orig, encoding="utf-8")
    _ensure_angular_material_in_package_json(tmp_path)
    assert pkg.read_text(encoding="utf-8") == orig


def test_ensure_angular_material_in_package_json_no_package_json(tmp_path: Path) -> None:
    """When package.json does not exist, no error."""
    _ensure_angular_material_in_package_json(tmp_path)
    assert not (tmp_path / "package.json").exists()


def test_ensure_material_theme_in_styles_adds_theme_when_missing(tmp_path: Path) -> None:
    """When styles.scss has no Material theme, it is prepended."""
    src = tmp_path / "src"
    src.mkdir()
    styles = src / "styles.scss"
    styles.write_text("/* custom */\nbody { margin: 0; }\n", encoding="utf-8")
    _ensure_material_theme_in_styles(tmp_path)
    content = styles.read_text(encoding="utf-8")
    assert "@use '@angular/material/prebuilt-themes/indigo-pink.css'" in content
    assert "/* custom */" in content


def test_ensure_material_theme_in_styles_noop_when_present(tmp_path: Path) -> None:
    """When styles.scss already has Material theme, it is unchanged."""
    src = tmp_path / "src"
    src.mkdir()
    orig = "@use '@angular/material/prebuilt-themes/indigo-pink.css';\nbody { margin: 0; }\n"
    styles = src / "styles.scss"
    styles.write_text(orig, encoding="utf-8")
    _ensure_material_theme_in_styles(tmp_path)
    assert styles.read_text(encoding="utf-8") == orig


def test_ensure_material_theme_in_styles_no_styles_file(tmp_path: Path) -> None:
    """When no styles file exists, no error."""
    _ensure_material_theme_in_styles(tmp_path)
    assert not (tmp_path / "src" / "styles.scss").exists()


def test_ensure_provide_animations_in_config_adds_when_missing(tmp_path: Path) -> None:
    """When app.config.ts lacks provideAnimations, it is added."""
    app = tmp_path / "src" / "app"
    app.mkdir(parents=True)
    config = app / "app.config.ts"
    config.write_text(
        """import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(),
  ],
};
""",
        encoding="utf-8",
    )
    _ensure_provide_animations_in_config(tmp_path)
    content = config.read_text(encoding="utf-8")
    assert "provideAnimations" in content
    assert "provideAnimations()" in content


def test_ensure_provide_animations_in_config_noop_when_present(tmp_path: Path) -> None:
    """When app.config.ts already has provideAnimations, it is unchanged."""
    app = tmp_path / "src" / "app"
    app.mkdir(parents=True)
    orig = """import { provideAnimations } from '@angular/platform-browser/animations';
export const appConfig = { providers: [provideAnimations()] };
"""
    config = app / "app.config.ts"
    config.write_text(orig, encoding="utf-8")
    _ensure_provide_animations_in_config(tmp_path)
    assert config.read_text(encoding="utf-8") == orig


def test_ensure_provide_animations_in_config_no_config_file(tmp_path: Path) -> None:
    """When app.config.ts does not exist, no error."""
    _ensure_provide_animations_in_config(tmp_path)
    assert not (tmp_path / "src" / "app" / "app.config.ts").exists()


@patch("shared.command_runner.run_command_with_nvm", return_value=CommandResult(success=True, exit_code=0, stdout="", stderr=""))
@patch("shared.command_runner._get_nvm_script_prefix", return_value="source ~/.nvm/nvm.sh")
def test_ensure_frontend_dependencies_calls_repairs(
    _mock_nvm: object, _mock_run: object, tmp_path: Path
) -> None:
    """ensure_frontend_dependencies_installed runs repair helpers before npm install."""
    pkg = tmp_path / "package.json"
    pkg.write_text('{"dependencies": {}}', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "styles.scss").write_text("", encoding="utf-8")
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "app.config.ts").write_text(
        """import { provideHttpClient } from '@angular/common/http';
export const appConfig = { providers: [provideHttpClient(),] };
""",
        encoding="utf-8",
    )
    result = ensure_frontend_dependencies_installed(tmp_path)
    assert result.success
    data = __import__("json").loads(pkg.read_text(encoding="utf-8"))
    assert "@angular/material" in data.get("dependencies", {})


@patch("shared.command_runner.run_command", return_value=CommandResult(success=True, exit_code=0, stdout="", stderr=""))
@patch("shared.command_runner.run_command_with_nvm", return_value=CommandResult(success=True, exit_code=0, stdout="", stderr=""))
@patch("shared.command_runner._get_nvm_script_prefix", return_value=None)
def test_ensure_frontend_project_initialized_creates_environment_files(
    _mock_nvm: object, _mock_nvm_run: object, mock_run: object, tmp_path: Path
) -> None:
    """ensure_frontend_project_initialized creates src/environments/environment.ts and environment.prod.ts."""
    result = ensure_frontend_project_initialized(tmp_path)
    assert result.success
    env_dir = tmp_path / "src" / "environments"
    assert env_dir.exists()
    env_ts = env_dir / "environment.ts"
    env_prod = env_dir / "environment.prod.ts"
    assert env_ts.exists()
    assert env_prod.exists()
    assert "apiUrl" in env_ts.read_text(encoding="utf-8")
    assert "production: true" in env_prod.read_text(encoding="utf-8")
