// ── RouteErrorPage ────────────────────────────────────────────
// Shown via React Router's `errorElement` when a route-level
// error occurs (e.g. loader failure, component crash).

import { useRouteError, useNavigate } from "react-router-dom";

export function RouteErrorPage() {
    const error = useRouteError() as Error | { message?: string; status?: number } | null;
    const navigate = useNavigate();

    const message =
        error && "message" in error ? error.message : "不明なエラーが発生しました";

    return (
        <div className="flex min-h-[60vh] items-center justify-center p-6">
            <div className="max-w-lg rounded-xl border border-red-200 bg-red-50 p-8 text-center shadow-sm">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
                    <svg
                        className="h-6 w-6 text-red-600"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={1.5}
                        stroke="currentColor"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
                        />
                    </svg>
                </div>
                <h2 className="text-base font-semibold text-red-800">
                    ページの表示中にエラーが発生しました
                </h2>
                <p className="mt-2 text-sm text-red-600">{message}</p>
                <div className="mt-6 flex items-center justify-center gap-3">
                    <button
                        onClick={() => navigate(0)}
                        className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors"
                    >
                        再試行
                    </button>
                    <button
                        onClick={() => navigate("/")}
                        className="rounded-md border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 transition-colors"
                    >
                        ホームに戻る
                    </button>
                </div>
            </div>
        </div>
    );
}
