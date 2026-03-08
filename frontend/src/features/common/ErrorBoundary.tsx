// ── ErrorBoundary ─────────────────────────────────────────────
// Catches React render errors and shows a user-friendly fallback
// instead of raw stack traces.

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
    children: ReactNode;
    /** Optional fallback to render instead of the default UI */
    fallback?: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        console.error("[ErrorBoundary] caught:", error, errorInfo);
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: null });
    };

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) {
                return this.props.fallback;
            }

            return (
                <div className="flex min-h-[200px] items-center justify-center p-6">
                    <div className="max-w-md rounded-xl border border-red-200 bg-red-50 p-6 text-center shadow-sm">
                        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
                            <svg
                                className="h-5 w-5 text-red-600"
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
                        <h3 className="text-sm font-semibold text-red-800">
                            予期しないエラーが発生しました
                        </h3>
                        <p className="mt-1 text-xs text-red-600">
                            {this.state.error?.message || "不明なエラー"}
                        </p>
                        <div className="mt-4 flex items-center justify-center gap-2">
                            <button
                                onClick={this.handleRetry}
                                className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 transition-colors"
                            >
                                再試行
                            </button>
                            <button
                                onClick={() => window.location.reload()}
                                className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 transition-colors"
                            >
                                ページを再読み込み
                            </button>
                        </div>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}
