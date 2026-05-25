#!/bin/bash
# MiniClaw 一键打包脚本
# 产出: miniclaw-portable.tar.gz — 解压即可用

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
BUILD_DIR="$SCRIPT_DIR/build"
VENV_DIR="$BUILD_DIR/miniclaw-portable/.venv"
DIST_FILE="$SCRIPT_DIR/miniclaw-portable.tar.gz"

echo "🦫 MiniClaw 打包开始..."

# 1. 清理旧构建
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# 2. 复制项目文件
echo "📦 复制项目文件..."
cp -r "$PROJECT_DIR/miniclaw" "$BUILD_DIR/miniclaw-portable/"
cp "$PROJECT_DIR/pyproject.toml" "$BUILD_DIR/miniclaw-portable/"
cp "$PROJECT_DIR/requirements.txt" "$BUILD_DIR/miniclaw-portable/"
cp "$PROJECT_DIR/miniclaw.toml" "$BUILD_DIR/miniclaw-portable/"
cp -r "$PROJECT_DIR/workspace" "$BUILD_DIR/miniclaw-portable/"
cp -r "$PROJECT_DIR/skills" "$BUILD_DIR/miniclaw-portable/"
mkdir -p "$BUILD_DIR/miniclaw-portable/data/sessions"

# 3. 创建虚拟环境并安装依赖
echo "📦 创建虚拟环境..."
python3 -m venv "$VENV_DIR"

echo "📦 安装依赖（这可能需要几分钟）..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet
pip install -r "$BUILD_DIR/miniclaw-portable/requirements.txt" --quiet
deactivate

# 4. 写启动脚本
echo "📝 写启动脚本..."
cat > "$BUILD_DIR/miniclaw-portable/miniclaw.sh" << 'LAUNCH'
#!/bin/bash
# MiniClaw 启动脚本
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"
PYTHONPATH="$SCRIPT_DIR" python -m miniclaw "$@"
LAUNCH
chmod +x "$BUILD_DIR/miniclaw-portable/miniclaw.sh"

# 5. 打包
echo "📦 压缩打包..."
cd "$BUILD_DIR"
tar czf "$DIST_FILE" miniclaw-portable/

# 6. 报告
SIZE=$(du -sh "$DIST_FILE" | cut -f1)
echo ""
echo "✅ 打包完成！"
echo "   文件: $DIST_FILE"
echo "   大小: $SIZE"
echo ""
echo "使用方法:"
echo "  tar xzf miniclaw-portable.tar.gz"
echo "  cd miniclaw-portable"
echo "  编辑 miniclaw.toml 填入 API key"
echo "  ./miniclaw.sh chat"
