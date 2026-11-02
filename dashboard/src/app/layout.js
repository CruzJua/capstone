import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { TenantProvider } from "@/context/TenantContext";
import AppShell from "@/components/AppShell";

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
                <AuthProvider>
                    <TenantProvider>
                        <AppShell>{children}</AppShell>
                    </TenantProvider>
                </AuthProvider>
            </body>
        </html>
    );
}
