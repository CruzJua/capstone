import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { TenantProvider } from "@/context/TenantContext";
import AppShell from "@/components/AppShell";

// Fonts ship inside the "geist" package, so builds never fetch them from Google Fonts.
// They expose the same --font-geist-sans / --font-geist-mono variables globals.css uses.
const geistSans = GeistSans;
const geistMono = GeistMono;

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
