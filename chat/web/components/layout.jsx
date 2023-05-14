import React from 'react'
import Head from 'next/head'
import styles from './layout.module.css'

const Layout = ({ children }) => {
  return (
    <div className={styles.container}>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      </Head>
      <header className={styles.header}>Header</header>
      <main className={styles.main}>{children}</main>
      <footer className={styles.footer}>Footer</footer>
    </div>
  )
}

export default Layout