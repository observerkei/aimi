import yaml
import logging
import colorlog
import inspect
import os
import importlib
import json5

from typing import Dict, List, Generator


def log_disable():
    global __log_disable
    __log_disable = True


def log_init():
    global __log_disable
    if __log_disable:
        return None

    # 创建一个 logger 对象
    logger = logging.getLogger(__name__)

    # 设置 logger 的日志级别
    logger.setLevel(logging.DEBUG)

    # 设置日志输出格式
    coler_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)-5s%(reset)s %(message)s",
        datefmt=None,
        reset=True,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
        secondary_log_colors={},
        style="%",
    )

    """
    # 创建 FileHandler 对象，并设置日志文件路径、文件名称和日志输出级别
    #log_file = './run/aimi.log'
    file_handler = logging.StreamHandler() #logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # 将 formatter 设置为 handler 的格式化器
    file_handler.setFormatter(coler_formatter)

    # 将 FileHandler 添加到 logger 对象中
    logger.addHandler(file_handler)

    """

    # 将 colorlog 添加到 logger 对象中
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(coler_formatter)
    logger.addHandler(stream_handler)

    # logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

    logger.propagate = False  # 禁止日志信息向父级传递

    return logger


def log_err(message: str, is_plugin: bool = False):
    global __log_disable
    if __log_disable:
        return None
    caller_file = get_caller_filename(is_plugin)
    caller_func = get_caller_function_name(is_plugin)
    caller_line = get_caller_lineno(is_plugin)
    logger.error(f"[{caller_file}:{caller_func}:{caller_line}]  {message}")


def log_dbg(message: str, is_plugin: bool = False):
    global __log_disable
    if __log_disable:
        return None
    caller_file = get_caller_filename(is_plugin)
    caller_func = get_caller_function_name(is_plugin)
    caller_line = get_caller_lineno(is_plugin)
    logger.debug(f"[{caller_file}:{caller_func}:{caller_line}]  {message}")
    # import traceback
    # traceback.print_stack()

def log_info(message: str, is_plugin: bool = False):
    global __log_disable
    if __log_disable:
        return None
    caller_file = get_caller_filename(is_plugin)
    caller_func = get_caller_function_name(is_plugin)
    caller_line = get_caller_lineno(is_plugin)
    logger.info(f"[{caller_file}:{caller_func}:{caller_line}]  {message}")



def get_caller_filename(is_plugin: bool = False):
    frame = inspect.stack()[2] if not is_plugin else inspect.stack()[3]
    filename = frame[0].f_code.co_filename
    return os.path.splitext(os.path.basename(filename))[0]


def get_caller_function_name(is_plugin: bool = False):
    stack = inspect.stack()
    frame = stack[2] if not is_plugin else stack[3]
    info = inspect.getframeinfo(frame[0])
    return info.function


def get_caller_lineno(is_plugin: bool = False):
    lineno = inspect.currentframe().f_back.f_back.f_lineno
    lineno = (
        lineno
        if not is_plugin
        else inspect.currentframe().f_back.f_back.f_back.f_lineno
    )
    return lineno


def read_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        obj = yaml.load(f.read(), Loader=yaml.FullLoader)
    return obj


def write_yaml(path: str, obj: dict):
    with open(path, "w", encoding="utf-8") as fp:
        yaml.dump(obj, fp, encoding="utf-8", allow_unicode=True)


def make_context_messages(
    question: str, preset: str = "", talk_history: List[Dict] = []
) -> List[Dict]:
    if not preset:
        preset = ""
    if not talk_history:
        talk_history = []

    context_messages = []
    if len(preset):
        context_messages = [{"role": "system", "content": preset}]
    context_messages.extend(talk_history)
    if len(question):
        context_messages.append({"role": "user", "content": question})

    return context_messages


def is_json(data):
    try:
        json5.loads(str(data))
    except ValueError as e:
        return False
    return True


def load_module(
    module_path: str, load_name: List[str], file_start: str = "", file_end: str = ".py"
) -> Generator[dict, None, None]:
    if not module_path.endswith("/"):
        module_path += "/"

    # 遍历目录中的文件
    for filename in os.listdir(module_path):
        # 如果文件名以指定前缀开头并且是 Python 脚本
        if (not len(file_start) or filename.startswith(file_start)) and (
            not len(file_end) or filename.endswith(file_end)
        ):
            # 使用 importlib 加载模块
            module_name = filename[:-3]  # 去掉 .py 后缀
            load_module_path = os.path.join(module_path, filename)  # 补全路径

            module = None
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name, load_module_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                log_err(f"fail to load {filename} : {str(e)}")
                continue

            # 实例化模块中的类
            for check_name in load_name:
                if not hasattr(module, check_name):
                    log_err(f"load file: {filename} no load_name: {check_name}")
                    continue

            yield filename, module


def green_input(prompt: str):
    GREEN = "\033[92m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    return input(f"{GREEN}{BOLD}{prompt}{RESET}")


def move_key_to_first_position(dictionary: dict, key: str):
    if key not in dictionary:
        return dictionary
    value = dictionary.pop(key)
    dictionary = {key: value, **dictionary}
    return dictionary


__log_disable: bool = False

if not __log_disable:
    logger = log_init()
