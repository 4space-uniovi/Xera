#!/usr/bin/env bash
# Actualiza el rover desde GitHub: git pull + aplica los cambios (dependencias, udev, servicio).
#   ./update.sh               # pull y reinstala (pide sudo si hay que reiniciar el servicio)
#   ./update.sh --dry-run     # solo muestra qué commits llegarían, sin cambiar nada
# Tu configuración (rover/config/rover.yaml) no se toca: está fuera de git.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(git -C "$REPO" rev-parse --show-toplevel)"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

cd "$ROOT"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Tienes cambios locales sin guardar (git status). Haz commit o 'git stash' antes de actualizar:"
  git status --short | head -10; exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Rama: $BRANCH — buscando cambios..."
git fetch --quiet
UP="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
[ -n "$UP" ] || { echo "La rama $BRANCH no sigue ninguna rama remota (git branch -u origin/$BRANCH)."; exit 1; }

NEW="$(git log --oneline HEAD.."$UP")"
if [ -z "$NEW" ]; then echo "Ya estás al día."; [ "$DRY" = 1 ] && exit 0; else
  echo "Llegan estos cambios:"; echo "$NEW" | sed 's/^/  /'
fi
[ "$DRY" = 1 ] && exit 0

OLD_HEAD="$(git rev-parse HEAD)"
git pull --ff-only --quiet
echo "Actualizado: $(git rev-parse --short "$OLD_HEAD") → $(git rev-parse --short HEAD)"

# Qué cambió decide si hace falta reiniciar: solo frontend/docs => basta recargar la página.
CHANGED="$(git diff --name-only "$OLD_HEAD" HEAD -- rover | sed 's|^rover/||')"
if [ -n "$CHANGED" ] && ! echo "$CHANGED" | grep -vqE '^(frontend/|docs/|README)'; then
  echo "Solo cambió la interfaz web/documentación: recarga la página, no hace falta reiniciar."; exit 0
fi
exec "$REPO/scripts/install.sh" --yes
