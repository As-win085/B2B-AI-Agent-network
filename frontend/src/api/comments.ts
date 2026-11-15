import { apiRequest } from "./client";
import type { Comment, CommentPage } from "../types/comments";

export const MAX_COMMENT_LENGTH = 5000;

export async function listComments(postId: string, page: number): Promise<CommentPage> {
  const result = await apiRequest<{ data: Comment[]; meta?: Record<string, unknown> }>(
    `/api/v1/posts/${postId}/comments?page=${page}&page_size=10`,
    { includeMeta: true },
  );
  return {
    comments: result.data,
    page: Number(result.meta?.page ?? page),
    page_size: Number(result.meta?.page_size ?? 10),
    total: Number(result.meta?.total ?? result.data.length),
  };
}

export function createComment(postId: string, agentKey: string, content: string): Promise<Comment> {
  return apiRequest<Comment>(`/api/v1/posts/${postId}/comments`, {
    method: "POST",
    skipAuth: true,
    allowRefresh: false,
    headers: { Authorization: `Bearer ${agentKey}` },
    body: JSON.stringify({ content }),
  });
}

export function deleteComment(
  commentId: string,
  agentKey?: string,
): Promise<{ id: string; deleted: boolean }> {
  return apiRequest<{ id: string; deleted: boolean }>(`/api/v1/comments/${commentId}`, {
    method: "DELETE",
    ...(agentKey
      ? { skipAuth: true, allowRefresh: false, headers: { Authorization: `Bearer ${agentKey}` } }
      : {}),
  });
}
