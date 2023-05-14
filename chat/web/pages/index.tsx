import { Text, Page } from '@vercel/examples-ui'
import { Chat } from '../components/Chat'
import { Layout } from '../components/layout'
import footer from '../components/footer.module.css'

function Home() {
  return (
    <Page className={"flex flex-col gap-12 " + footer.father_footer }>
      <section className="flex flex-col gap-6">
        <Text variant="h1">Chat Aimi WEB</Text>
        <Text className={"text-zinc-600 "} >
          Aimi is Research robot assistant
        </Text>
      </section>

      <section className={"flex flex-col gap-3 w-full"}>
        <Text variant="h2">Chat:</Text>
        <div className="w-full">
          <Chat />
        </div>
      </section>
    </Page>
  )
}

export default Home
