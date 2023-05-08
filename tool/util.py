import yaml
import logging
import colorlog

def log_init():
    # 创建一个 logger 对象
    logger = logging.getLogger('my_logger')

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

    return logger

def log_err(message: str):
    logger.error(message)

def log_dbg(message: str):
    logger.debug(message)

def log_info(message: str):
    logger.info(message)

def read_yaml(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        obj = yaml.load(f.read(), Loader=yaml.FullLoader)
    return obj

def write_yaml(path: str, obj: dict):
    with open(path, 'w', encoding='utf-8') as fp:
        yaml.dump(obj, fp, encoding='utf-8', allow_unicode=True)

logger = log_init()
