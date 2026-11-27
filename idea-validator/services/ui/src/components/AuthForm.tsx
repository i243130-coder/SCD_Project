import { useState } from "react";

export function AuthForm({ onSubmit }: { onSubmit: (mode: "login" | "register", email: string, password: string) => Promise<void> }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email)) return setError("Enter a valid email");
    if (password.length < 8) return setError("Password must be at least 8 characters");
    setError(null);
    try {
      await onSubmit(mode, email, password);
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form onSubmit={submit} className="max-w-sm mx-auto mt-16 space-y-3 bg-white p-6 rounded shadow">
      <h1 className="text-xl font-semibold">{mode === "login" ? "Log in" : "Create account"}</h1>
      <input aria-label="email" className="border p-2 w-full" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email" />
      <input aria-label="password" type="password" className="border p-2 w-full" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" />
      {error && <p role="alert" className="text-red-600 text-sm">{error}</p>}
      <button className="bg-indigo-600 text-white px-4 py-2 rounded w-full">{mode === "login" ? "Log in" : "Register"}</button>
      <button type="button" className="text-sm underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
        {mode === "login" ? "No account? Register" : "Have an account? Log in"}
      </button>
    </form>
  );
}
