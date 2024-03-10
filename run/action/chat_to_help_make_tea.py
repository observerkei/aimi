
from core.task import ActionToolItem


s_action = ActionToolItem(
    call="chat_to_help_make_tea",
    description="帮助泡牛奶的动作的解释说明：这个动作的作用是帮助用户泡牛奶, 需要提供杯子、热水和牛奶, 然后按照一定的顺序倒入杯子中即可。",
    request="{'type': 'object', 'step': '帮助泡牛奶的步骤: 1. 准备一个空杯子; 2. 加入热水; 3. 加入牛奶。'}",
    execute="system",
)

def chat_from(request):
  print('请准备一个空杯子')
  print('加入热水')
  print('加入牛奶')