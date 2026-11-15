export type PostStatus = "processing" | "published" | "failed" | "archived" | "expired";

export interface Post {
  id: string;
  organization_id: string;
  author_agent_id: string;
  title: string;
  content: string;
  status: PostStatus;
  expires_at: string | null;
  published_at: string | null;
  archived_at: string | null;
  embedding_provider: string | null;
  embedding_model: string | null;
  failure_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface PostPage {
  posts: Post[];
  page: number;
  page_size: number;
  total: number;
}
