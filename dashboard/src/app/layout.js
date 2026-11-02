import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { TenantProvider } from "@/context/TenantContext";
import Sidebar from "@/components/Sidebar";

const geistSans = Geist({
    variable: "--font-geist-sans",
    subsets: ["latin"],
});

const geistMono = Geist_Mono({
    variable: "--font-geist-mono",
    subsets: ["latin"],
});

export const metadata = {
    title: "Support Admin Console | Multi-Tenant RAG Gateway",
    description:
        "Self-hosted multi-tenant customer support administration console for managing knowledge bases, tenant identity, and local LLM runtime parameters.",
};

export default function RootLayout({ children }) {
    return (
        <html
            lang="en"
            className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
        >
            <body className="min-h-full bg-zinc-950 text-zinc-100">
                <TenantProvider>
                    <div className="min-h-screen flex flex-col lg:flex-row">
                        <Sidebar />
                        <div className="flex-1 flex flex-col min-w-0">
                            {children}
                        </div>
                    </div>
                </TenantProvider>
            </body>
        </html>
    );
}
