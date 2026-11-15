import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PostsPage } from "../pages/PostsPage";

const mocks = vi.hoisted(() => ({ listPosts: vi.fn(), createPost: vi.fn() }));

vi.mock("../api/posts", () => ({
  archivePost: vi.fn(),
  createPost: mocks.createPost,
  listPosts: mocks.listPosts,
}));

vi.mock("../features/auth/authContext", () => ({
  useAuth: () => ({ organization: { role: "owner" } }),
}));

const post = {
  id: "post-1",
  organization_id: "org-1",
  author_agent_id: "agent-1",
  title: "Launch update",
  content: "A business update",
  status: "processing" as const,
  expires_at: null,
  published_at: null,
  archived_at: null,
  embedding_provider: null,
  embedding_model: null,
  failure_code: null,
  created_at: "2026-11-15T00:00:00Z",
  updated_at: "2026-11-15T00:00:00Z",
};

describe("PostsPage", () => {
  beforeEach(() => {
    mocks.listPosts
      .mockReset()
      .mockResolvedValue({ posts: [post], page: 1, page_size: 10, total: 1 });
    mocks.createPost.mockReset().mockResolvedValue(post);
  });

  it("shows posts in the active workspace", async () => {
    render(<PostsPage />);
    expect(await screen.findByRole("heading", { name: "Launch update" })).toBeInTheDocument();
    expect(screen.getByText("processing")).toBeInTheDocument();
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
});
