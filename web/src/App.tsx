import { RouterProvider, createBrowserRouter } from "react-router-dom";
import { routes } from "./routes";
import { ThemeProvider } from "./context/ThemeContext";
import { WorkspaceProvider } from "./context/WorkspaceContext";

const router = createBrowserRouter(routes);

export default function App() {
  return (
    <ThemeProvider>
      <WorkspaceProvider>
        <RouterProvider router={router} />
      </WorkspaceProvider>
    </ThemeProvider>
  );
}
