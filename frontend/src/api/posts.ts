import { apiRequest } from "./client";
import type { Post, PostPage } from "../types/posts";

export async function listPosts(page: number): Promise<PostPage> {
  const result = await apiRequest<{ data: Post[]; meta?: Record<string, unknown> }>(
    `/api/v1/posts?page=${page}&page_size=10`,
    { includeMeta: true },
  );
  return {
    posts: result.data,
    page: Number(result.meta?.page ?? page),
    page_size: Number(result.meta?.page_size ?? 10),
    total: Number(result.meta?.total ?? result.data.length),
  };
}

export function createPost(
  key: string,
  input: { title: string; content: string; expires_at?: string },
): Promise<Post> {
  return apiRequest<Post>("/api/v1/posts", {
    method: "POST",
    skipAuth: true,
    allowRefresh: false,
    headers: { Authorization: `Bearer ${key}` },
    body: JSON.stringify(input),
  });
}

export function archivePost(id: string): Promise<Post> {
  return apiRequest<Post>(`/api/v1/posts/${id}`, { method: "DELETE" });
}
