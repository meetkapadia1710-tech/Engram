#!/usr/bin/env bash
#
# supermemory-server installer.
#
#   curl -fsSL https://supermemory.ai/install | bash
#
# Detects your OS+arch, downloads the matching binary from the
# supermemoryai/supermemory GitHub Releases, verifies sha256, and (if run
# interactively) asks for an LLM API key. Writes a small wrapper at
# ~/.local/bin/supermemory-server that sources ~/.supermemory/env then
# exec's the binary.
#
# Optional env vars / args:
#   $1                       — "latest" (default) or explicit version like "0.0.1"
#   SUPERMEMORY_INSTALL_DIR  — base dir (default: $HOME/.supermemory)
#   SUPERMEMORY_BIN_DIR      — wrapper dir (default: $HOME/.local/bin)
#   OPENAI_API_KEY /         — if any of these are exported before running,
#   GEMINI_API_KEY /            the prompt is skipped and they're written into
#   ANTHROPIC_API_KEY            ~/.supermemory/env as-is.
#   SUPERMEMORY_NO_START=1   — install only; do not start the server.
#   SUPERMEMORY_NO_PROMPT=1  — never prompt (API key step is skipped).
#   SUPERMEMORY_FORCE=1      — reinstall even if the same version is present.
#

set -euo pipefail

REPO="supermemoryai/supermemory"
BIN_NAME="supermemory-server"
RELEASES_URL="https://github.com/$REPO/releases"
INSTALL_DIR="${SUPERMEMORY_INSTALL_DIR:-$HOME/.supermemory}"
BIN_DIR="${SUPERMEMORY_BIN_DIR:-$HOME/.local/bin}"
TARGET="${1:-latest}"
INSTALL_OWNER=""
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_UID:-}" ] && [ -n "${SUDO_GID:-}" ]; then
	INSTALL_OWNER="$SUDO_UID:$SUDO_GID"
fi

# --- helpers ---------------------------------------------------------------

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "→ $*"; }
ok() { echo "✓ $*"; }

fix_owner() {
	[ -n "$INSTALL_OWNER" ] || return 0
	chown -R "$INSTALL_OWNER" "$1" 2>/dev/null || true
}

secure_dir() {
	mkdir -p "$1"
	chmod u+rwx,go-rwx "$1" 2>/dev/null || true
	fix_owner "$1"
}

if command -v curl >/dev/null 2>&1; then
	dl() { curl -fsSL "$1" -o "$2"; }
	dlstdout() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
	dl() { wget -q "$1" -O "$2"; }
	dlstdout() { wget -q -O - "$1"; }
else
	die "curl or wget required"
fi

sha256() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	elif command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" | awk '{print $1}'
	else
		die "sha256sum or shasum required"
	fi
}

repair_macos_signature() {
	[ "$os" = "darwin" ] || return 0
	command -v codesign >/dev/null 2>&1 || return 0
	if codesign --verify --verbose=4 "$1" >/dev/null 2>&1; then
		return 0
	fi
	info "Repairing macOS code signature..."
	codesign --force --sign - "$1" >/dev/null 2>&1 \
		|| die "failed to sign $BIN_NAME with ad-hoc macOS signature"
	codesign --verify --verbose=4 "$1" >/dev/null 2>&1 \
		|| die "failed to verify repaired macOS signature"
	ok "Repaired macOS code signature"
}

# Determines whether the script can read user input. When piped from curl,
# stdin is the script body — we re-attach /dev/tty to read prompts.
have_tty() {
	[ "${SUPERMEMORY_NO_PROMPT:-}" != "1" ] && [ -r /dev/tty ] && [ -w /dev/tty ]
}

should_auto_start() {
	[ "${SUPERMEMORY_NO_START:-}" != "1" ] \
		&& [ "${SUPERMEMORY_SKIP_START:-}" != "1" ] \
		&& have_tty
}

# --- detect platform ------------------------------------------------------

case "$(uname -s)" in
	Darwin) os="darwin" ;;
	Linux)  os="linux" ;;
	*) die "unsupported OS: $(uname -s)" ;;
esac

case "$(uname -m)" in
	x86_64|amd64) arch="x64" ;;
	arm64|aarch64) arch="arm64" ;;
	*) die "unsupported architecture: $(uname -m)" ;;
esac

# Rosetta 2 — Intel binary on Apple Silicon. Prefer native arm64.
if [ "$os" = "darwin" ] && [ "$arch" = "x64" ] \
	&& [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = "1" ]; then
	arch="arm64"
fi

platform="${os}-${arch}"
info "Platform: $platform"

# --- resolve version ------------------------------------------------------

version=""
if [ "$TARGET" = "latest" ]; then
	# Prefer the /releases/latest redirect — unlike the REST API it is not
	# rate-limited, so install bursts (and CI) don't 403.
	if command -v curl >/dev/null 2>&1; then
		final_url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$RELEASES_URL/latest" 2>/dev/null || true)
		version=$(printf '%s' "$final_url" \
			| sed -nE 's#.*/releases/tag/server-v([0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?)$#\1#p')
	fi
fi

if [ "$TARGET" = "latest" ] && [ -z "$version" ]; then
	# Fallback: REST API listing (also used when only wget is available, and
	# while no stable release exists yet — /latest ignores prereleases).
	# Prefer the newest stable release; fall back to the newest prerelease.
	if command -v jq >/dev/null 2>&1; then
		api_url="https://api.github.com/repos/$REPO/releases?per_page=20"
		version=$(dlstdout "$api_url" | jq -r '
			[.[]
			 | select(.draft|not)
			 | select(.tag_name | test("^server-v[0-9]+\\.[0-9]+\\.[0-9]+(-[A-Za-z0-9.]+)?$"))
			] as $all
			| (([$all[] | select(.prerelease|not)][0]) // $all[0]).tag_name // empty
		' | sed -n 's/^server-v//p')
	else
		version=$(dlstdout "https://api.github.com/repos/$REPO/releases?per_page=20" \
			| tr -d '\n' \
			| grep -oE '"tag_name":[[:space:]]*"server-v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?"' \
			| head -1 \
			| sed -E 's/.*"server-v([0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?)".*/\1/')
	fi
	[ -n "$version" ] || die "could not resolve latest version from $RELEASES_URL"
fi
[ "$TARGET" = "latest" ] || version="$TARGET"

info "Version: $version"
tag="server-v$version"
asset_base="$RELEASES_URL/download/$tag"

# --- skip when already up to date -------------------------------------------

version_file="$INSTALL_DIR/bin/$BIN_NAME.version"
installed_version=""
if [ -f "$version_file" ]; then
	installed_version=$(cat "$version_file" 2>/dev/null || true)
fi
if [ "${SUPERMEMORY_FORCE:-}" != "1" ] \
	&& [ -n "$installed_version" ] \
	&& [ "$installed_version" = "$version" ] \
	&& [ -x "$INSTALL_DIR/bin/$BIN_NAME" ]; then
	ok "supermemory-server v$version is already installed — nothing to do"
	info "Force a reinstall by re-running with SUPERMEMORY_FORCE=1 set."
	exit 0
fi

# --- download manifest + verify --------------------------------------------

secure_dir "$INSTALL_DIR"
secure_dir "$INSTALL_DIR/bin"
secure_dir "$INSTALL_DIR/downloads"
manifest_path="$INSTALL_DIR/downloads/manifest-$version.json"
dl "$asset_base/manifest.json" "$manifest_path" \
	|| die "manifest.json not found for $tag (does the release exist?)"

if command -v jq >/dev/null 2>&1; then
	checksum=$(jq -r ".platforms[\"$platform\"].checksum // empty" "$manifest_path")
else
	# Brittle fallback: extract checksum string for our platform from the manifest.
	checksum=$(tr -d '\n\r\t ' < "$manifest_path" \
		| grep -oE "\"$platform\":\\{\"checksum\":\"[a-f0-9]{64}\"" \
		| grep -oE '[a-f0-9]{64}' | head -1)
fi
[[ "$checksum" =~ ^[a-f0-9]{64}$ ]] \
	|| die "no checksum for $platform in manifest"

# --- download + verify binary ----------------------------------------------

bin_dl="$INSTALL_DIR/downloads/${BIN_NAME}-${platform}-${version}"
info "Downloading $BIN_NAME-$platform..."
dl "$asset_base/${BIN_NAME}-${platform}" "$bin_dl" \
	|| die "binary download failed"

actual=$(sha256 "$bin_dl")
[ "$actual" = "$checksum" ] || die "checksum mismatch (expected $checksum, got $actual)"
ok "Verified sha256"

chmod +x "$bin_dl"
repair_macos_signature "$bin_dl"
final_bin="$INSTALL_DIR/bin/$BIN_NAME"
mv -f "$bin_dl" "$final_bin"
fix_owner "$final_bin"
printf '%s\n' "$version" > "$version_file"
fix_owner "$version_file"
ok "Installed binary → $final_bin"

# --- API key prompt -------------------------------------------------------

env_file="$INSTALL_DIR/env"
write_env_line() {
	local k="$1" v="$2"
	# Avoid duplicates: drop any prior line for the same key.
	if [ -f "$env_file" ]; then
		grep -v "^${k}=" "$env_file" > "$env_file.tmp" && mv "$env_file.tmp" "$env_file" || true
	fi
	printf "%s='%s'\\n" "$k" "${v//\'/\'\\\'\'}" >> "$env_file"
	chmod 600 "$env_file"
	fix_owner "$env_file"
}

prefill_count=0
for k in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY; do
	v="${!k:-}"
	if [ -n "$v" ]; then
		write_env_line "$k" "$v"
		ok "Wrote $k from environment → $env_file"
		prefill_count=$((prefill_count + 1))
	fi
done

if [ "$prefill_count" -eq 0 ]; then
	if have_tty; then
		echo
		echo "supermemory-server needs at least one LLM API key for embeddings/summaries."
		echo "Pick a provider (you can add more later by editing $env_file):"
		echo "  1) OpenAI         (OPENAI_API_KEY)"
		echo "  2) Anthropic      (ANTHROPIC_API_KEY)"
		echo "  3) Gemini         (GEMINI_API_KEY)"
		echo "  4) Skip for now"
		printf "Choice [1-4]: " > /dev/tty
		read -r choice < /dev/tty
		case "$choice" in
			1) key_name="OPENAI_API_KEY" ;;
			2) key_name="ANTHROPIC_API_KEY" ;;
			3) key_name="GEMINI_API_KEY" ;;
			*) key_name="" ;;
		esac
		if [ -n "$key_name" ]; then
			printf "Paste your %s: " "$key_name" > /dev/tty
			read -r key_value < /dev/tty
			if [ -n "$key_value" ]; then
				write_env_line "$key_name" "$key_value"
				ok "Saved $key_name → $env_file (mode 600)"
			fi
		fi
	else
		info "Non-interactive install — no API key written."
		info "Add one to $env_file before first run, e.g.:"
		info "  echo 'OPENAI_API_KEY=sk-...' >> $env_file && chmod 600 $env_file"
	fi
fi

# --- wrapper script -------------------------------------------------------

mkdir -p "$BIN_DIR"
wrapper="$BIN_DIR/$BIN_NAME"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
# Auto-generated by supermemory-server installer.
# Sources $env_file then exec's the real binary.
set -a
[ -f "$env_file" ] && . "$env_file"
set +a
exec "$final_bin" "\$@"
EOF
chmod +x "$wrapper"
if [ -z "${SUPERMEMORY_BIN_DIR:-}" ]; then
	fix_owner "$BIN_DIR"
fi
ok "Installed wrapper → $wrapper"

# --- PATH guidance --------------------------------------------------------

case ":$PATH:" in
	*:"$BIN_DIR":*) on_path=1 ;;
	*) on_path=0 ;;
esac

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ supermemory-server $version installed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$on_path" = "1" ]; then
	echo "  Start:  $BIN_NAME"
else
	echo "  Start:  $wrapper"
	echo
	echo "  ($BIN_DIR is not on \$PATH — add it to your shell rc:"
	echo "    echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc)"
fi
echo "  Data:   \$SUPERMEMORY_DATA_DIR or ./.supermemory/ (created on first run)"
echo "  Env:    $env_file"
echo "  Docs:   https://github.com/$REPO"
echo

if should_auto_start; then
	echo "Starting supermemory-server. Press Ctrl-C to stop it."
	echo
	if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_UID:-}" ]; then
		info "Not auto-starting as root. Start it as your user instead:"
		echo "  $wrapper"
		exit 0
	fi
	exec "$wrapper"
else
	echo "Start it with:"
	echo "  $wrapper"
	echo
fi
