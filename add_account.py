import logging

import nte


def _ask_continue():
    while True:
        answer = input('是否继续添加账号？（Y/n）：').strip().lower()
        if answer in {'', 'y', 'yes'}:
            return True
        if answer in {'n', 'no'}:
            return False
        print('输入无效，请输入 Y 或 N。')


def main():
    try:
        with nte.account_file_lock():
            _main()
    except OSError as ex:
        print(f'账号文件暂不可用：{ex}')


def _main():
    print('塔吉多（异环）账号添加工具')
    nte.config_logger()

    accounts = nte.read(nte.token_save_name)
    print(f'当前 TOKEN.txt 中已有 {len(accounts)} 个账号。')

    while True:
        try:
            account = nte.input_for_token()
        except Exception as ex:
            print(f'添加账号失败，原因：{ex}')
            logging.error('添加账号失败', exc_info=ex)
            if not _ask_continue():
                break
            continue

        accounts.append(account)
        nte.save(accounts)
        print(f'已保存，当前共有 {len(accounts)} 个账号。')

        if not _ask_continue():
            break

    print('账号添加完成。')


if __name__ == '__main__':
    main()
