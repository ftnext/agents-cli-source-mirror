# Release Notes 解説の作り方 — Claude への指示書

google-agents-cli wheel ミラーで、バージョン間のリリースノートを「実装解説つき」markdown に
展開し、GitHub release のドラフトまで作るための再利用可能な指示書。

## 入力 (呼び出し時に与えられる)

- **対象バージョン**: 旧 `X.Y.Z` と新 `X.Y.W`。
- **リリースノートの箇条書き本文**: 呼び出し時に与えられる。自分で探さず、与えられた文面・順序を正とする。

## タスク指示 (Claude にコピペするテキスト)

> `X.Y.Z` から `X.Y.W` への差分から、以下のリリースノートを詳しく解説してください。
> （ここに箇条書きを貼る）
> 箇条書き1つを1セクションに変換し、実装の解説を markdown に書き出してください。
> 英語版 `release-notes-X.Y.W.en.md` も作成し、最後に `gh` で GitHub release を
> ドラフト作成して完了としてください。

---

## 手順

### 1. 対象バージョンの2コミットを特定する
1バージョン = 1 import コミット。コミットメッセージは `Import google-agents-cli X.Y.Z wheel contents` 形式。

```bash
git log --oneline --all | grep -i 'Import google-agents-cli'
# 例: BASE=acc9995 (0.1.2), HEAD=75dece0 (0.1.3)
```

### 2. 変更ファイルを俯瞰する
```bash
git diff <BASE> <HEAD> --stat
```

### 3. 各箇条書きを diff で裏取りする
箇条書き → ファイルの対応づけが `--stat` で分からなければ、特徴的な語句で grep する。

```bash
git diff <BASE> <HEAD> | grep -in 'terraform\|plan\|apply'   # 語句は項目に応じて
git diff <BASE> <HEAD> -- <path/to/file.py>                  # 当たったら項目単位で精読
```

### 4. markdown を書き出す
- ファイル名: `release-notes-X.Y.W.md` (日本語) と `release-notes-X.Y.W.en.md` (英語)。
- 各箇条書き = 1セクション。順序はリリースノートの並びを維持。構成は下記テンプレート参照。

### 5. 完了：`gh` で GitHub release をドラフト作成する
**英語版**を本文に使い、先頭に Full Changelog 比較リンクを足す。既存ドラフト (`v0.1.3`) の規約に揃える。

```bash
{
  echo "**Full Changelog**: https://github.com/ftnext/agents-cli-source-mirror/compare/vX.Y.Z...vX.Y.W"
  echo
  cat release-notes-X.Y.W.en.md
} > /tmp/release-body-X.Y.W.md

gh release create vX.Y.W --draft --prerelease \
  --title "vX.Y.W (AI annotated release note)" \
  --notes-file /tmp/release-body-X.Y.W.md
```

`--draft` 止まりで publish しない。tag 未 push でも untagged draft として作成できる。
作成後 `gh release view vX.Y.W` で確認する。

---

## セクション構成テンプレート (1項目 = 1セクション)

「### 概要」(何がどう変わったか。before/after を 1〜2段落) と
「### 実装」(変更ファイルを `path/to/file.py` で明記、新設の関数/フラグ/定数を名前つきで列挙、
重要箇所は短いコードブロックで引用、設計意図コメントがあれば引用) の2本立て。0.1.3 の記入例:

```markdown
## 4. `agents-cli info` で OS 情報を表示 (バグ報告を楽にするため)

### 概要
`agents-cli info` (および `--json`) の出力にホスト OS の情報を追加。
ユーザが issue を立てるときに OS 情報をすぐコピペできるようにする狙い。

### 実装 (`google/agents/cli/info/cmd_info.py`)
- 標準ライブラリの `platform` をインポート。
- `os_info = platform.platform()` で `Darwin-25.4.0-...` のような統合文字列を取得。
- JSON / テキストの全出力経路に反映 (プロジェクト検出時・未検出時の両方)。
- 表示位置は `CLI install path` の直後、`installed_skills` の前。
```

## 品質の指針

- 推測せず diff を根拠に書く。読んでいない箇所を断定しない。
- diff から追えない項目 (scaffold される SKILL.md など wheel 非収録のもの。例: 0.1.3 の
  "Update skills to cover need for cloud sql role") は埋めず、「差分から確認できない」と明記する。
- バグ修正は「なぜ壊れていたか (根本原因) → どう直したか」の順で書く。
- 日英は同じ構成・同じ詳細度に揃える。コード・パス・引用は両言語とも原文 (英語) のまま。
