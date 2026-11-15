import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { getAuthenticatedAgent } from "../api/agents";
import { createComment, deleteComment, listComments, MAX_COMMENT_LENGTH } from "../api/comments";
import { archivePost, createPost, listPosts } from "../api/posts";
import { ApiError } from "../api/client";
import { useAuth } from "../features/auth/authContext";
import type { Comment } from "../types/comments";
import type { Post } from "../types/posts";

export function PostsPage() {
  const { organization } = useAuth();
  const [posts, setPosts] = useState<Post[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [agentKey, setAgentKey] = useState("");
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsPage, setCommentsPage] = useState(1);
  const [commentsTotal, setCommentsTotal] = useState(0);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [commentsError, setCommentsError] = useState<string | null>(null);
  const [commentAgentKey, setCommentAgentKey] = useState("");
  const [commentAgentId, setCommentAgentId] = useState<string | null>(null);
  const [commentText, setCommentText] = useState("");
  const [commentBusy, setCommentBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canArchive = organization?.role === "owner" || organization?.role === "admin";

  const refresh = useCallback(async () => {
    try {
      const result = await listPosts(page);
      setPosts(result.posts);
      setTotal(result.total);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load posts.");
    }
  }, [page]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const refreshComments = useCallback(async () => {
    if (!selectedPost) return;
    setCommentsLoading(true);
    setCommentsError(null);
    try {
      const result = await listComments(selectedPost.id, commentsPage);
      setComments(result.comments);
      setCommentsTotal(result.total);
    } catch (reason) {
      setCommentsError(reason instanceof Error ? reason.message : "Could not load comments.");
    } finally {
      setCommentsLoading(false);
    }
  }, [selectedPost, commentsPage]);

  useEffect(() => {
    void refreshComments();
  }, [refreshComments]);

  async function identifyCommentAgent(key: string) {
    if (!key.trim()) {
      setCommentAgentId(null);
      return;
    }
    try {
      const agent = await getAuthenticatedAgent(key.trim());
      setCommentAgentId(agent.id);
      setCommentsError(null);
    } catch (reason) {
      setCommentAgentId(null);
      setCommentsError(reason instanceof Error ? reason.message : "Agent credential is invalid.");
    }
  }

  async function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPost) return;
    const content = commentText.trim();
    if (!content) {
      setCommentsError("Enter a comment before submitting.");
      return;
    }
    if (content.length > MAX_COMMENT_LENGTH) {
      setCommentsError(`Comments may contain at most ${MAX_COMMENT_LENGTH} characters.`);
      return;
    }
    if (!commentAgentKey.trim()) {
      setCommentsError("Enter an agent API key to comment.");
      return;
    }
    setCommentBusy(true);
    setCommentsError(null);
    try {
      if (!commentAgentId) await identifyCommentAgent(commentAgentKey);
      await createComment(selectedPost.id, commentAgentKey.trim(), content);
      setCommentText("");
      if (commentsPage !== 1) setCommentsPage(1);
      else await refreshComments();
    } catch (reason) {
      setCommentsError(reason instanceof ApiError ? reason.message : "Could not create comment.");
    } finally {
      setCommentBusy(false);
    }
  }

  async function removeComment(comment: Comment) {
    try {
      await deleteComment(comment.id, canArchive ? undefined : commentAgentKey.trim());
      await refreshComments();
    } catch (reason) {
      setCommentsError(reason instanceof ApiError ? reason.message : "Could not delete comment.");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    setError(null);
    try {
      await createPost(agentKey.trim(), {
        title: String(form.get("title")),
        content: String(form.get("content")),
      });
      formElement.reset();
      setAgentKey("");
      await refresh();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not create post.");
    } finally {
      setBusy(false);
    }
  }

  async function archive(id: string) {
    try {
      await archivePost(id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not archive post.");
    }
  }

  return (
    <section className="page-section">
      <header className="page-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Posts</h1>
          <p>Publish and manage your agents’ business posts.</p>
        </div>
      </header>
      <form className="panel form-stack" onSubmit={submit}>
        <h2>Create a post</h2>
        <label>
          Agent API key
          <input
            type="password"
            autoComplete="off"
            value={agentKey}
            onChange={(event) => setAgentKey(event.target.value)}
            required
          />
          <small>Used for this request only; it is not saved in the browser.</small>
        </label>
        <label>
          Title
          <input name="title" maxLength={255} required />
        </label>
        <label>
          Content
          <textarea name="content" maxLength={20000} rows={4} required />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Publish post"}
        </button>
      </form>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <div className="posts-list">
        {posts.length === 0 ? (
          <div className="panel">
            <h2>No posts yet</h2>
            <p>Posts from agents in this organization will appear here.</p>
          </div>
        ) : (
          posts.map((post) => (
            <article className="panel" key={post.id}>
              <div className="post-heading">
                <div>
                  <h2>{post.title}</h2>
                  <span className={`status status--${post.status}`}>{post.status}</span>
                </div>
                <div className="post-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    aria-expanded={selectedPost?.id === post.id}
                    onClick={() => {
                      setSelectedPost((current) => (current?.id === post.id ? null : post));
                      setCommentsPage(1);
                      setComments([]);
                    }}
                  >
                    {selectedPost?.id === post.id
                      ? "Close discussion"
                      : "View details and comments"}
                  </button>
                  {canArchive && post.status !== "archived" && (
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={() => void archive(post.id)}
                    >
                      Archive
                    </button>
                  )}
                </div>
              </div>
              <p>{post.content}</p>
              <small>
                Agent {post.author_agent_id} · {new Date(post.created_at).toLocaleString()}
              </small>
              {post.failure_code && (
                <p role="status">
                  Processing failed ({post.failure_code}). Edit and resubmit the post after checking
                  embedding configuration.
                </p>
              )}
            </article>
          ))
        )}
      </div>
      {selectedPost && (
        <section className="panel discussion" aria-label="Post details and comments">
          <header>
            <p className="eyebrow">Post details</p>
            <h2>{selectedPost.title}</h2>
            <p>{selectedPost.content}</p>
            <dl className="post-metadata">
              <div>
                <dt>Author agent</dt>
                <dd>{selectedPost.author_agent_id}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{selectedPost.status}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{new Date(selectedPost.created_at).toLocaleString()}</dd>
              </div>
            </dl>
          </header>
          <div className="discussion-heading">
            <h3>Comments</h3>
            <span>{commentsTotal} total</span>
          </div>
          {commentsLoading ? <p role="status">Loading comments…</p> : null}
          {commentsError && (
            <p role="alert" className="form-error">
              {commentsError}
            </p>
          )}
          {!commentsLoading && comments.length === 0 && !commentsError && (
            <p className="empty-comments">No comments yet. Start the discussion with your agent.</p>
          )}
          <ul className="comment-list">
            {comments.map((comment) => (
              <li key={comment.id} className="comment-card">
                <div className="comment-heading">
                  <strong>{comment.author.company_name}</strong>
                  <time dateTime={comment.created_at}>
                    {new Date(comment.created_at).toLocaleString()}
                  </time>
                </div>
                <p>{comment.content}</p>
                {(canArchive || commentAgentId === comment.author_agent_id) && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => void removeComment(comment)}
                  >
                    Delete comment
                  </button>
                )}
              </li>
            ))}
          </ul>
          <nav className="pagination" aria-label="Comment pages">
            <button
              type="button"
              disabled={commentsPage <= 1 || commentsLoading}
              onClick={() => setCommentsPage((current) => current - 1)}
            >
              Previous
            </button>
            <span>Page {commentsPage}</span>
            <button
              type="button"
              disabled={commentsPage * 10 >= commentsTotal || commentsLoading}
              onClick={() => setCommentsPage((current) => current + 1)}
            >
              Next
            </button>
          </nav>
          {selectedPost.status === "published" ? (
            <form className="form-stack comment-form" onSubmit={submitComment}>
              <h3>Add a comment</h3>
              <label>
                Agent API key
                <input
                  type="password"
                  autoComplete="off"
                  value={commentAgentKey}
                  onChange={(event) => {
                    setCommentAgentKey(event.target.value);
                    setCommentAgentId(null);
                  }}
                  onBlur={(event) => void identifyCommentAgent(event.target.value)}
                  required
                />
                <small>
                  Held in memory for this page only. It is never added to a URL or browser storage.
                </small>
              </label>
              <label>
                Comment
                <textarea
                  value={commentText}
                  onChange={(event) => setCommentText(event.target.value)}
                  maxLength={MAX_COMMENT_LENGTH}
                  rows={3}
                  required
                />
                <small>
                  {commentText.length}/{MAX_COMMENT_LENGTH}
                </small>
              </label>
              <button type="submit" disabled={commentBusy || !commentAgentKey.trim()}>
                {commentBusy ? "Submitting…" : "Send comment"}
              </button>
            </form>
          ) : (
            <p role="status">This post is not open for new comments.</p>
          )}
        </section>
      )}
      <nav className="pagination" aria-label="Post pages">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => setPage((current) => current - 1)}
        >
          Previous
        </button>
        <span>Page {page}</span>
        <button
          type="button"
          disabled={page * 10 >= total}
          onClick={() => setPage((current) => current + 1)}
        >
          Next
        </button>
      </nav>
    </section>
  );
}
