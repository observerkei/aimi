import yaml
import logging
import colorlog
import inspect
import os

def log_init():
    # 创建一个 logger 对象
    logger = logging.getLogger(__name__)

    # 设置 logger 的日志级别
    logger.setLevel(logging.DEBUG)

    # 设置日志输出格式
    coler_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(message)s",
        datefmt = None,
        reset = True,
        log_colors = {
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red',
        },
        secondary_log_colors = {},
        style = '%'
    )

    '''
    # 创建 FileHandler 对象，并设置日志文件路径、文件名称和日志输出级别
    #log_file = './run/aimi.log'
    file_handler = logging.StreamHandler() #logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # 将 formatter 设置为 handler 的格式化器
    file_handler.setFormatter(coler_formatter)

    # 将 FileHandler 添加到 logger 对象中
    logger.addHandler(file_handler)

    '''

    # 将 colorlog 添加到 logger 对象中
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(coler_formatter)
    logger.addHandler(stream_handler)

    #logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

    logger.propagate = False  # 禁止日志信息向父级传递

    return logger


def log_err(message: str, is_plugin:bool = False):
    caller_file = get_caller_filename(is_plugin)
    caller_func = get_caller_function_name(is_plugin)
    caller_line = get_caller_lineno(is_plugin)
    logger.error(f"[{caller_file}:{caller_func}:{caller_line}] {message}")

def log_dbg(message: str, is_plugin:bool = False):
    caller_file = get_caller_filename(is_plugin)
    caller_func = get_caller_function_name(is_plugin)
    caller_line = get_caller_lineno(is_plugin)
    logger.debug(f"[{caller_file}:{caller_func}:{caller_line}] {message}")

def log_info(message: str, is_plugin:bool = False):
    caller_file = get_caller_filename(is_plugin)
    caller_func = get_caller_function_name(is_plugin)
    caller_line = get_caller_lineno(is_plugin)
    logger.info(f"[{caller_file}:{caller_func}:{caller_line}] {message}")

def get_caller_filename(is_plugin:bool = False):
    frame = inspect.stack()[2] if not is_plugin else inspect.stack()[3]
    filename = frame[0].f_code.co_filename
    return os.path.basename(filename)

def get_caller_function_name(is_plugin:bool = False):
    stack = inspect.stack()
    frame = stack[2] if not is_plugin else stack[3]
    info = inspect.getframeinfo(frame[0])
    return info.function

def get_caller_lineno(is_plugin:bool = False):
    lineno = inspect.currentframe().f_back.f_back.f_lineno
    lineno = lineno if not is_plugin else inspect.currentframe().f_back.f_back.f_back.f_lineno
    return lineno

def read_yaml(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        obj = yaml.load(f.read(), Loader=yaml.FullLoader)
    return obj

def write_yaml(path: str, obj: dict):
    with open(path, 'w', encoding='utf-8') as fp:
        yaml.dump(obj, fp, encoding='utf-8', allow_unicode=True)

logger = log_init()
