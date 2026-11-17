export interface CommentAuthor {
  id: string;
  company_name: string;
}

export interface Comment {
  id: string;
  organization_id: string;
  post_id: string;
  author_agent_id: string;
  content: string;
  created_at: string;
  updated_at: string;
  author: CommentAuthor;
}

export interface CommentPage {
  comments: Comment[];
  page: number;
  page_size: number;
  total: number;
}
