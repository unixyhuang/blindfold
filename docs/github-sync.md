# 更新 GitHub 仓库

目标仓库为 [unixyhuang/blindfold](https://github.com/unixyhuang/blindfold)，默认分支是 `main`。

## 本地修改后同步

在包含 `main.py` 的目录执行：

```sh
python scripts/sync_github.py --message "Update artifact"
```

脚本会初始化当前目录的 Git 仓库（首次使用时）、连接目标仓库、提交当前目录的改动并推送当前分支。已存在的 Git 署名设置会被沿用。若本机尚未设置署名，会在当前仓库设置 `Xinyu Huang` 和 GitHub noreply 邮箱 `118581397+unixyhuang@users.noreply.github.com`。

首次推送前需要登录 GitHub。Windows Git Credential Manager 可以使用设备登录：

```sh
git credential-manager github login --username unixyhuang --device --no-ui
```

按命令输出的地址和验证码完成网页登录。若远端出现了本地尚未获取的提交，推送会停止。先运行 `git pull --rebase origin main` 并处理可能的冲突，再执行同步命令。

## 推送后的自动流程

GitHub Actions 会运行两个桌面示例，核对目标状态，然后打包 ZIP。在仓库的 [Actions 页面](https://github.com/unixyhuang/blindfold/actions) 打开成功的运行，即可下载 `blindfold-artifact`。Actions 文件保留 30 天。

如需一个可长期引用的版本下载，在确认当前提交可发布后运行：

```sh
git tag v0.1.0
git push origin v0.1.0
```

`v*` 标签会触发独立的 Release job，生成 Release 并附上 ZIP。新版本使用新的标签名。

## 发布前需要作者填写的信息

- 代码 LICENSE 的选择。
- README 中希望公开的维护者联系方式。
- 七个论文 prompt 占位文件中准备公开的正文。
- 论文原始实现与当前桌面示例之间的覆盖范围说明。

当前仓库提供可运行的桌面符号示例及本地 Ollama 客户端。完整论文实现的状态见 [README](../README.md)。
