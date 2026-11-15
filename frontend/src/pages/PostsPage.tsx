import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { archivePost, createPost, listPosts } from "../api/posts";
import { ApiError } from "../api/client";
import { useAuth } from "../features/auth/authContext";
import type { Post } from "../types/posts";

export function PostsPage() {
  const { organization } = useAuth();
  const [posts, setPosts] = useState<Post[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [agentKey, setAgentKey] = useState("");
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
