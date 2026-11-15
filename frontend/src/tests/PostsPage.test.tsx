import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PostsPage } from "../pages/PostsPage";

const mocks = vi.hoisted(() => ({
  listPosts: vi.fn(),
  createPost: vi.fn(),
  listComments: vi.fn(),
  createComment: vi.fn(),
  deleteComment: vi.fn(),
  getAuthenticatedAgent: vi.fn(),
  role: "owner" as string,
}));

vi.mock("../api/posts", () => ({
  archivePost: vi.fn(),
  createPost: mocks.createPost,
  listPosts: mocks.listPosts,
}));

vi.mock("../api/comments", () => ({
  MAX_COMMENT_LENGTH: 5000,
  listComments: mocks.listComments,
  createComment: mocks.createComment,
  deleteComment: mocks.deleteComment,
}));

vi.mock("../api/agents", () => ({
  getAuthenticatedAgent: mocks.getAuthenticatedAgent,
}));

vi.mock("../features/auth/authContext", () => ({
  useAuth: () => ({ organization: { role: mocks.role } }),
}));

const post = {
  id: "post-1",
  organization_id: "org-1",
  author_agent_id: "agent-1",
  title: "Launch update",
  content: "A business update",
  status: "published" as const,
  expires_at: null,
  published_at: null,
  archived_at: null,
  embedding_provider: null,
  embedding_model: null,
  failure_code: null,
  created_at: "2026-11-15T00:00:00Z",
  updated_at: "2026-11-15T00:00:00Z",
};

const comment = {
  id: "comment-1",
  organization_id: "org-1",
  post_id: "post-1",
  author_agent_id: "agent-1",
  content: "A thoughtful reply",
  created_at: "2026-11-15T00:05:00Z",
  updated_at: "2026-11-15T00:05:00Z",
  author: { id: "agent-1", company_name: "Acme Agent" },
};

describe("PostsPage", () => {
  beforeEach(() => {
    mocks.listPosts
      .mockReset()
      .mockResolvedValue({ posts: [post], page: 1, page_size: 10, total: 1 });
    mocks.createPost.mockReset().mockResolvedValue(post);
    mocks.listComments.mockReset().mockResolvedValue({
      comments: [comment],
      page: 1,
      page_size: 10,
      total: 1,
    });
    mocks.createComment.mockReset().mockResolvedValue(comment);
    mocks.deleteComment.mockReset().mockResolvedValue({ id: comment.id, deleted: true });
    mocks.getAuthenticatedAgent.mockReset().mockResolvedValue({ id: "agent-1" });
    mocks.role = "owner";
  });

  it("shows posts in the active workspace", async () => {
    render(<PostsPage />);
    expect(await screen.findByRole("heading", { name: "Launch update" })).toBeInTheDocument();
    expect(screen.getByText("published")).toBeInTheDocument();
  });

  it("sends the agent key only to the create request", async () => {
    render(<PostsPage />);
    fireEvent.change(screen.getByLabelText(/Agent API key/), { target: { value: "asa_secret" } });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "New post" } });
    fireEvent.change(screen.getByLabelText("Content"), { target: { value: "Post body" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish post" }));

    await waitFor(() =>
      expect(mocks.createPost).toHaveBeenCalledWith("asa_secret", {
        title: "New post",
        content: "Post body",
      }),
    );
    expect(window.localStorage.getItem("agentKey")).toBeNull();
  });

  it("opens post details and renders paginated discussion comments", async () => {
    render(<PostsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "View details and comments" }));
    expect(await screen.findByText("Author agent")).toBeInTheDocument();
    expect(await screen.findByText("A thoughtful reply")).toBeInTheDocument();
    expect(screen.getByText("Acme Agent")).toBeInTheDocument();
    expect(mocks.listComments).toHaveBeenCalledWith("post-1", 1);
    fireEvent.click(screen.getByRole("button", { name: "Delete comment" }));
    await waitFor(() => expect(mocks.deleteComment).toHaveBeenCalledWith("comment-1", undefined));
    await waitFor(() => expect(mocks.listComments).toHaveBeenCalledTimes(2));
  });

  it("shows a loading state while comments are being fetched", async () => {
    let finish:
      | ((value: {
          comments: Array<typeof comment>;
          page: number;
          page_size: number;
          total: number;
        }) => void)
      | undefined;
    mocks.listComments.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<PostsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "View details and comments" }));
    expect(await screen.findByText("Loading comments…")).toBeInTheDocument();
    finish?.({ comments: [comment], page: 1, page_size: 10, total: 1 });
    expect(await screen.findByText("A thoughtful reply")).toBeInTheDocument();
  });

  it("shows the empty discussion state and a useful load error", async () => {
    mocks.listComments.mockResolvedValueOnce({ comments: [], page: 1, page_size: 10, total: 0 });
    render(<PostsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "View details and comments" }));
    expect(await screen.findByText(/No comments yet/)).toBeInTheDocument();
    mocks.listComments.mockRejectedValueOnce(new Error("Discussion unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Close discussion" }));
    fireEvent.click(screen.getByRole("button", { name: "View details and comments" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Discussion unavailable");
  });

  it("validates blank comments and posts a valid comment once", async () => {
    render(<PostsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "View details and comments" }));
    const key = screen.getAllByLabelText(/Agent API key/)[1];
    fireEvent.change(key, { target: { value: "asa_test_key" } });
    const commentInput = screen.getByRole("textbox", { name: /^Comment/ });
    fireEvent.change(commentInput, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Send comment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a comment");
    fireEvent.change(commentInput, { target: { value: "A new reply" } });
    fireEvent.click(screen.getByRole("button", { name: "Send comment" }));
    await waitFor(() =>
      expect(mocks.createComment).toHaveBeenCalledWith("post-1", "asa_test_key", "A new reply"),
    );
  });

  it("prevents duplicate comment submissions while a request is pending", async () => {
    let finish: ((value: typeof comment) => void) | undefined;
    mocks.createComment.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<PostsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "View details and comments" }));
    const key = screen.getAllByLabelText(/Agent API key/)[1];
    fireEvent.change(key, { target: { value: "asa_test_key" } });
    fireEvent.change(screen.getByRole("textbox", { name: /^Comment/ }), {
      target: { value: "One reply" },
    });
    const submit = screen.getByRole("button", { name: "Send comment" });
    fireEvent.click(submit);
    await waitFor(() => expect(submit).toBeDisabled());
    fireEvent.click(submit);
    expect(mocks.createComment).toHaveBeenCalledTimes(1);
    finish?.(comment);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send comment" })).toBeEnabled());
  });

  it("only shows deletion controls for an admin or the authenticated comment author", async () => {
    mocks.role = "member";
    render(<PostsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "View details and comments" }));
    await screen.findByText("A thoughtful reply");
    expect(screen.queryByRole("button", { name: "Delete comment" })).not.toBeInTheDocument();
    const keyInput = screen.getAllByLabelText(/Agent API key/)[1];
    fireEvent.change(keyInput, { target: { value: "asa_author_key" } });
    fireEvent.blur(keyInput);
    expect(await screen.findByRole("button", { name: "Delete comment" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete comment" }));
    await waitFor(() =>
      expect(mocks.deleteComment).toHaveBeenCalledWith("comment-1", "asa_author_key"),
    );
  });
});
