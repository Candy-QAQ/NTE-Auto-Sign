"""
塔吉多（异环）自动签到
name: 塔吉多（异环）自动签到
cron: 0 8 * * *
"""

import os
import sys

# 强制使用青龙面板环境变量 NTE_TOKEN，避免与其它脚本共用的 TOKEN 冲突；
# 此处把 NTE_TOKEN 的值映射到 nte 期望的 TOKEN。
_ntoken = os.environ.get('NTE_TOKEN')
if _ntoken:
    os.environ['TOKEN'] = _ntoken

import nte


def main():
    nte.config_logger()
    if not nte.token_env:
        print('未配置账号：请在青龙面板“环境变量”中添加 NTE_TOKEN（多账号用换行分隔，格式同 TOKEN.txt）。')
        return False
    return nte.start()


if __name__ == '__main__':
    print('塔吉多（异环）自动签到')
    sys.exit(0 if main() else 1)