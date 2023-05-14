import { useEffect, useState, useRef } from 'react'
import { Button } from './Button'
import { type ChatGPTMessage, ChatLine, LoadingChatLine } from './ChatLine'
import { useCookies } from 'react-cookie'
import styles from './footer.module.css'
import style_input from './input_text.module.css'
import chatline from './chatline.module.css'
import { json } from 'stream/consumers'

const COOKIE_NAME = 'nextjs-example-ai-chat-gpt3'

// default first message to display in UI (not necessary to define the prompt)
export const initialMessages: ChatGPTMessage[] = [
  {
    role: 'assistant',
    content: 'Hi! I am a friendly AI assistant. Ask me anything!',
  },
]


const InputMessage = ({ input, setInput, sendMessage }: any) => {
  const [value, setValue] = useState("");
  const inputRef = useRef(null);

  function handleKeyDown(event) {
    if (event.key === "Enter" && event.shiftKey) {
      event.preventDefault();
      const start = event.target.selectionStart;
      const end = event.target.selectionEnd;
      setValue((value) => {
        return value.substring(0, start) + "\n" + value.substring(end);
      });
      event.target.selectionStart = event.target.selectionEnd = start + 1;
    } else if (event.key === "Enter") {
      event.preventDefault();
      sendMessage(value.trim());
      setValue("");
    }
  }

  function handleInputChange(event) {
    setValue(event.target.value);
  }

  useEffect(() => {
    const inputEl = inputRef.current;
    inputEl.style.height = "auto";
    inputEl.style.height = `${Math.min(
      inputEl.scrollHeight,
      Math.floor(window.innerHeight / 3)
    )}px`;
  }, [value]);

  return (
    <div className={"mt-6 flex clear-both mb-5 " + styles.children_footer}>
      <textarea
        className={
          style_input.send_input +
          " min-w-0 flex-auto appearance-none rounded-md border border-zinc-900/10 bg-white px-3 py-[calc(theme(spacing.2)-1px)] shadow-md shadow-zinc-800/5 placeholder:text-zinc-400 focus:border-teal-500 focus:outline-none focus:ring-4 focus:ring-teal-500/10 sm:text-sm"
        }
        value={value}
        ref={inputRef}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        rows={1}
      />
      <Button
        type="submit"
        className="ml-4 flex-none"
        onClick={() => {
          sendMessage(value.trim());
          setValue("");
        }}
      >
        {"Send"}
      </Button>
    </div>
  );
};


export function Chat() {
  const [messages, setMessages] = useState<ChatGPTMessage[]>(initialMessages)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [cookie, setCookie] = useCookies([COOKIE_NAME])
  const lastMessageRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!cookie[COOKIE_NAME]) {
      // generate a semi random short id
      const randomId = Math.random().toString(36).substring(7)
      setCookie(COOKIE_NAME, randomId)
    }
  }, [cookie, setCookie])

  useEffect(() => {
    if (!loading) {
      const loadingElement = document.getElementById('loading-chat-line');
      if (loadingElement) {
        loadingElement.scrollIntoView({ behavior: 'smooth' });
      }
    } else if (lastMessageRef.current) {
      lastMessageRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, loading]);

  // send message to API /api/chat endpoint
  const sendMessage = async (message: string) => {
    setLoading(true)
    const newMessages = [
      ...messages,
      { role: 'user', content: message } as ChatGPTMessage,
    ]
    setMessages(newMessages)
    const last10messages = newMessages.slice(-10) // remember last 10 messages

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        messages: last10messages,
        user: cookie[COOKIE_NAME],
      }),
    })

    console.log('Edge function returned.')

    if (!response.ok) {
      throw new Error(response.statusText)
    }

    // This data is a ReadableStream
    const data = response.body
    if (!data) {
      return
    }
    
    console.log('get response: ' + JSON.stringify(response))
    console.log('get response.body: ' + JSON.stringify(response.body))

    const reader = data.getReader()
    const decoder = new TextDecoder()
    let done = false

    let lastMessage = ''

    while (!done) {
      const { value, done: doneReading } = await reader.read()
      done = doneReading
      const chunkValue = decoder.decode(value)

      lastMessage = lastMessage + chunkValue
      console.log('get lastMessage: ' + JSON.stringify(lastMessage))

      setMessages([
        ...newMessages,
        { role: 'assistant', content: lastMessage } as ChatGPTMessage,
      ])
      

      setLoading(false)
    }
  }

  return (
    <div className="rounded-2xl border-zinc-100  lg:border lg:p-6 w-full">
      {messages.map(({ content, role }, index) => (
        <ChatLine key={index} role={role} content={content} />
      ))}

      {loading && <LoadingChatLine id="loading-chat-line" />}

      {messages.length < 2 && (
        <span className="mx-auto flex flex-grow text-gray-600 clear-both">
          Type a message to start the conversation
        </span>
      )}

      <div className={"float-right clear-both h-[2cm] bg-transparent "} ></div>
      
      <InputMessage
        input={input}
        setInput={setInput}
        sendMessage={sendMessage}
      />

      <div ref={lastMessageRef} />
    </div>
  )
}