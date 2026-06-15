// Catches uncaught render errors so a single field-shape mismatch doesn't
// blank the whole page. Renders the error message + stack instead.
import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Surface to the browser console so you can see it in DevTools too.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] caught', error, info);
  }

  reset = () => {
    this.setState({ error: null, info: null });
  };

  render() {
    if (!this.state.error) return this.props.children;
    const { error, info } = this.state;
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <div className="bg-red-50 border border-red-300 rounded-lg p-5">
          <div className="text-red-800 font-semibold mb-2">
            Something went wrong rendering this page.
          </div>
          <div className="text-sm text-red-700 font-mono break-words">
            {String(error?.message || error)}
          </div>
          {info?.componentStack && (
            <details className="mt-3">
              <summary className="text-xs cursor-pointer text-red-700">
                Component stack
              </summary>
              <pre className="text-xs text-slate-700 mt-2 whitespace-pre-wrap">
                {info.componentStack}
              </pre>
            </details>
          )}
          <div className="mt-4 flex gap-2">
            <button
              onClick={this.reset}
              className="px-3 py-1.5 text-sm rounded bg-red-600 hover:bg-red-700 text-white"
            >
              Retry
            </button>
            <button
              onClick={() => window.location.assign('/')}
              className="px-3 py-1.5 text-sm rounded border border-red-300 text-red-700 hover:bg-red-50"
            >
              Go home
            </button>
          </div>
        </div>
      </div>
    );
  }
}
