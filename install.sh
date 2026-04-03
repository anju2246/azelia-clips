#!/usr/bin/env bash

set -e # Exit on error

# Terminal Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${BLUE}"
cat << "EOF"
  █████╗ ███████╗███████╗██╗     ██╗ █████╗
 ██╔══██╗╚══███╔╝██╔════╝██║     ██║██╔══██╗
 ███████║  ███╔╝ █████╗  ██║     ██║███████║
 ██╔══██║ ███╔╝  ██╔══╝  ██║     ██║██╔══██║
 ██║  ██║███████╗███████╗███████╗██║██║  ██║
 ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝
EOF
echo -e "${NC}"
echo -e "${GREEN}${BOLD}Bienvenido al instalador de Azelia Clips.${NC}\n"

# ─────────────────────────────────────────────
# 1. System Requirements Check & Install
# ─────────────────────────────────────────────
echo -e "${BLUE}[1/6] Verificando dependencias del sistema...${NC}"

check_cmd() {
    command -v "$1" &> /dev/null
}

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS — install missing deps via Homebrew
    if ! check_cmd brew; then
        echo -e "${YELLOW}Homebrew no encontrado. Instalando...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi

    for pkg in git python3 node ffmpeg; do
        if ! check_cmd "$pkg"; then
            echo "Instalando $pkg vía Homebrew..."
            brew install "$pkg" > /dev/null 2>&1
        else
            echo "✓ $pkg detectado."
        fi
    done
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux — check only, don't auto-install
    missing=()
    for pkg in git python3 node ffmpeg; do
        if ! check_cmd "$pkg"; then
            missing+=("$pkg")
        else
            echo "✓ $pkg detectado."
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "${RED}Faltan dependencias: ${missing[*]}${NC}"
        echo -e "Instálalas con tu package manager (apt, dnf, pacman, etc.) y vuelve a ejecutar."
        exit 1
    fi
else
    echo -e "${YELLOW}OS no reconocido. Asegúrate de tener git, python3 (3.11+), node, npm y ffmpeg instalados.${NC}"
fi

# Check Python version (3.11+ required)
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo -e "${RED}Python 3.11+ requerido. Tienes Python ${PYTHON_VERSION}.${NC}"
    echo -e "Actualiza con: brew install python3  (macOS)"
    exit 1
fi
echo "✓ Python ${PYTHON_VERSION}"

# ─────────────────────────────────────────────
# 2. Clone or Update Repository
# ─────────────────────────────────────────────
echo -e "\n${BLUE}[2/6] Descargando Azelia Clips...${NC}"

INSTALL_DIR="$HOME/.azelia"
REPO_URL="https://github.com/anju2246/azelia-clips.git"

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Carpeta $INSTALL_DIR ya existe. Actualizando..."
    cd "$INSTALL_DIR"
    git pull origin main --quiet 2>/dev/null || git pull --quiet
else
    if [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}$INSTALL_DIR existe pero no es un repo git. Eliminando...${NC}"
        rm -rf "$INSTALL_DIR"
    fi
    echo "Clonando repositorio en $INSTALL_DIR..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ─────────────────────────────────────────────
# 3. Python Virtual Environment + Dependencies
# ─────────────────────────────────────────────
echo -e "\n${BLUE}[3/6] Configurando entorno Python...${NC}"
echo -e "${YELLOW}(Puede tomar unos minutos)${NC}"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

pip install --upgrade pip --quiet
pip install -e ".[all]" --quiet
echo "✓ Backend e IA configurados."

# ─────────────────────────────────────────────
# 4. Supabase Configuration
# ─────────────────────────────────────────────
echo -e "\n${BLUE}[4/6] Configuración de Supabase (obligatorio)...${NC}"
echo -e "${YELLOW}Azelia necesita un proyecto Supabase para auth y datos.${NC}"
echo -e "${YELLOW}Obtén estos valores en: https://supabase.com/dashboard → tu proyecto → Settings → API${NC}\n"

ENV_FILE="$INSTALL_DIR/.env"

if [ -f "$ENV_FILE" ] && grep -q "SUPABASE_URL=https://" "$ENV_FILE"; then
    echo "✓ Configuración de Supabase ya existente en .env."
    SUPABASE_URL=$(grep "^SUPABASE_URL=" "$ENV_FILE" | cut -d= -f2-)
    SUPABASE_KEY=$(grep "^SUPABASE_KEY=" "$ENV_FILE" | cut -d= -f2-)
else
    read -r -p "  SUPABASE_URL (ej: https://xyz.supabase.co): " SUPABASE_URL
    read -r -p "  SUPABASE_ANON_KEY (clave pública anon):      " SUPABASE_KEY

    if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
        echo -e "${RED}Las credenciales de Supabase son obligatorias. Abortando.${NC}"
        exit 1
    fi

    # Write root .env
    cat > "$ENV_FILE" << ENVFILE
# ─── Supabase ────────────────────────────────────────────────────────────────
SUPABASE_URL=$SUPABASE_URL
SUPABASE_KEY=$SUPABASE_KEY

# ─── AI Providers (configura al menos uno desde el dashboard) ───────────────
AI_PROVIDER_ORDER=anthropic,groq,openai,vertex
ANTHROPIC_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
GCP_PROJECT_ID=

# ─── Podcast config ──────────────────────────────────────────────────────────
PODCAST_DIR=.

# ─── Features ────────────────────────────────────────────────────────────────
AZELIA_TELEMETRY_ENABLED=false
ENVFILE
    echo "✓ .env creado."
fi

# ─────────────────────────────────────────────
# 5. Frontend Build
# ─────────────────────────────────────────────
echo -e "\n${BLUE}[5/6] Construyendo interfaz web (Astro/React)...${NC}"

cd web
npm install --silent 2>/dev/null
# Pass Supabase vars so Astro bakes them into the build
PUBLIC_SUPABASE_URL="$SUPABASE_URL" PUBLIC_SUPABASE_ANON_KEY="$SUPABASE_KEY" npm run build --silent 2>/dev/null
cd ..
echo "✓ Dashboard construido."

# ─────────────────────────────────────────────
# 5. Global Command Setup
# ─────────────────────────────────────────────
echo -e "\n${BLUE}[6/6] Instalando comando global 'azelia'...${NC}"

BIN_DIR="$HOME/.azelia/bin"
mkdir -p "$BIN_DIR"

# Wrapper script that activates venv and calls the real azelia entry point
cat << 'WRAPPER' > "$BIN_DIR/azelia"
#!/usr/bin/env bash
AZELIA_HOME="$HOME/.azelia"
source "$AZELIA_HOME/venv/bin/activate"
exec "$AZELIA_HOME/venv/bin/python" -m packages.clips.cli "$@"
WRAPPER
chmod +x "$BIN_DIR/azelia"

# Add to PATH if needed
add_to_path() {
    local shell_rc="$1"
    local path_line="export PATH=\"\$HOME/.azelia/bin:\$PATH\""
    if [ -f "$shell_rc" ]; then
        if ! grep -q '.azelia/bin' "$shell_rc" 2>/dev/null; then
            echo "" >> "$shell_rc"
            echo "# Azelia Clips" >> "$shell_rc"
            echo "$path_line" >> "$shell_rc"
            echo "  Añadido a $(basename "$shell_rc")"
        fi
    fi
}

if [[ ":$PATH:" == *":$BIN_DIR:"* ]]; then
    echo "✓ Ya está en el PATH."
else
    add_to_path "$HOME/.zshrc"
    add_to_path "$HOME/.bash_profile"
    add_to_path "$HOME/.bashrc"
    # Also export for this session
    export PATH="$BIN_DIR:$PATH"
    echo "✓ Comando añadido al PATH."
fi

# ─────────────────────────────────────────────
# Done!
# ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✨ Azelia Clips instalada exitosamente ✨${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Abre una terminal nueva y escribe:"
echo ""
echo -e "    ${BLUE}${BOLD}azelia start${NC}"
echo ""
echo -e "  ${YELLOW}(Si no funciona inmediatamente, cierra y abre la terminal)${NC}"
echo ""
