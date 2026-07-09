#!/bin/bash
# 部署脚本：将项目中的 hermes skills 同步到 hermes 识别的位置
# 使用方式：部署到服务器后运行一次 bash setup_hermes.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_SKILLS="$HOME/.hermes/skills"

echo "同步 hermes skills..."
echo "  源: $SCRIPT_DIR/.hermes/skills/"
echo "  目标: $HERMES_SKILLS/"

# 创建目标目录
mkdir -p "$HERMES_SKILLS"

# 复制所有 skills
for skill_dir in "$SCRIPT_DIR/.hermes/skills"/*; do
    if [ -d "$skill_dir" ]; then
        skill_name=$(basename "$skill_dir")
        target="$HERMES_SKILLS/$skill_name"
        
        # 如果目标已存在，先删除
        if [ -d "$target" ]; then
            rm -rf "$target"
        fi
        
        cp -r "$skill_dir" "$target"
        echo "  ✓ $skill_name"
    fi
done

echo "完成！已同步 $(ls -1 "$SCRIPT_DIR/.hermes/skills/" | wc -l) 个 skill"
echo ""
echo "验证："
cd "$SCRIPT_DIR" && hermes skills list | grep -E "gen-scraper|add-spider"
