export const metadata = { title: "Jace Social", description: "Friends, chat and hosted worlds for Jace Launcher" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", background: "#16181d", color: "#e6e8eb", margin: 0 }}>
        {children}
      </body>
    </html>
  );
}
