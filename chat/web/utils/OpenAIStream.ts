import {
  createParser,
  ParsedEvent,
  ReconnectInterval,
} from 'eventsource-parser'

export type ChatGPTAgent = 'user' | 'system' | 'assistant'

export interface ChatGPTMessage {
  role: ChatGPTAgent
  content: string
}

export interface OpenAIStreamPayload {
  model: string
  messages: ChatGPTMessage[]
  temperature: number
  top_p: number
  frequency_penalty: number
  presence_penalty: number
  max_tokens: number
  stream: boolean
  stop?: string[]
  user?: string
  n: number
}

let ask_bot_link:string = 'http://localhost:4642/api' //'https://api.openai.com/v1/chat/completions';

export async function OpenAIStream(payload: OpenAIStreamPayload) {
  const encoder = new TextEncoder()
  const decoder = new TextDecoder()

  let counter = 0

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${process.env.OPENAI_API_KEY ?? ''}`,
  }

  //if (process.env.OPENAI_API_ORG) {
  requestHeaders['OpenAI-Organization'] = 'fake_org'; //process.env.OPENAI_API_ORG
  //}

  console.log('try ask url: ' + ask_bot_link);
  console.log('try ask body: ' + JSON.stringify(payload));

  const res = await fetch(ask_bot_link, {
    headers: requestHeaders,
    method: 'POST',
    body: JSON.stringify(payload),
  })

  const stream = new ReadableStream({
    async start(controller) {
      // callback
      function onParse(event: ParsedEvent | ReconnectInterval) {
        console.log('try get event: ' + JSON.stringify(event))
        if (event.type === 'event') {
          console.log('event.type: ' + JSON.stringify(event.type))
          const data = event.data;
          console.log('event.data: ' + JSON.stringify(data))
          // https://beta.openai.com/docs/api-reference/completions/create#completions/create-stream
          if (data === '[DONE]') {
            console.log('DONE')
            controller.close()
            return
          }
          try {
            const json = JSON.parse(data)
            console.log('onParse.json: ' + JSON.stringify(json));
            console.log('onParse.json.choices: ' + JSON.stringify(json.choices));
            console.log('onParse.json.choices[0]: ' + JSON.stringify(json.choices[0]));
            console.log('onParse.json.choices[0].delta: ' + JSON.stringify(json.choices[0].delta));
            console.log('onParse.json.choices[0].delta?.content: ' + JSON.stringify(json.choices[0].delta?.content));
            
            const text = json.choices[0].delta?.content || ''
            //if (counter < 2 && (text.match(/\n/) || []).length) {
              // this is a prefix character (i.e., "\n\n"), do nothing
            //  return
            //}
            const queue = encoder.encode(text)
            controller.enqueue(queue)
            counter++
          } catch (e) {
            // maybe parse error
            controller.error(e)
          }
        }
      }

      console.log('par: 1')
      // stream response (SSE) from OpenAI may be fragmented into multiple chunks
      // this ensures we properly read chunks and invoke an event for each SSE event stream
      const parser = createParser(onParse)
      console.log('parser: ' + JSON.stringify(parser))
      for await (const chunk of res.body as any) {
        console.log('try get chunk: ' + JSON.stringify(chunk))
        let dec = decoder.decode(chunk)
        console.log('dec: ' + JSON.stringify(dec))
        parser.feed(dec)
        console.log('parser done: ' + JSON.stringify(parser))
      }
    },
  })

  return stream
}
