import re


class Language():
    language: str = 'zh'
    
    def __init__(self):
        pass
    

language = Language()

def has_chinese(s):
    """
    判断字符串中是否包含中文字符
    """
    pattern = re.compile('[\u4e00-\u9fa5]')
    result = pattern.search(s)
    return result is not None

def T(text: str) -> str:
    global language
    if (language.language == 'zh'):
        return 'zh str'
    if (language.language == 'en'):
        return 'en str'

def set_language(new_language: str):
    global language
    
    language.language = new_language

    