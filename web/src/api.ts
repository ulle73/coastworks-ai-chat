export type Bot = {
  id: string;
  url: string;
  state: "queued" | "reading" | "checking" | "ready" | "failed";
  message?: string;
  quality: { pages?: number };
  published: boolean;
};
export type Answer = {
  answer: string;
  sources: { url: string; title: string }[];
};
export async function api<T>(
  path: string,
  data?: unknown,
  token?: string,
): Promise<T> {
  const response = await fetch(path, {
    method: data === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: {
      ...(data !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Något gick fel. Kontrollera uppgifterna och försök igen.",
    );
  return result;
}
