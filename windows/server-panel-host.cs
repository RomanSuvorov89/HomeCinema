using System;
using System.Diagnostics;
using System.IO;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

internal static class WslPanelHost
{
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr window, int command);

    [STAThread]
    private static int Main()
    {
        string executable = Assembly.GetExecutingAssembly().Location;
        string root = Path.GetDirectoryName(executable);
        bool first;
        using (Mutex mutex = new Mutex(true, "Local\\WslPanel-" + Path.GetFileName(root), out first))
        {
            if (!first)
            {
                foreach (Process process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(executable)))
                {
                    using (process)
                    {
                        try
                        {
                            if (process.Id == Process.GetCurrentProcess().Id ||
                                !String.Equals(process.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase)) continue;
                            IntPtr window = process.MainWindowHandle;
                            if (window != IntPtr.Zero)
                            {
                                ShowWindow(window, 9); // Restore a minimized panel.
                                SetForegroundWindow(window);
                                return 0;
                            }
                        }
                        catch (System.ComponentModel.Win32Exception) { }
                    }
                }
                return 0;
            }
            try
            {
                using (Runspace runspace = RunspaceFactory.CreateRunspace())
                {
                    runspace.ApartmentState = ApartmentState.STA;
                    runspace.ThreadOptions = PSThreadOptions.UseCurrentThread;
                    runspace.Open();
                    Runspace.DefaultRunspace = runspace;
                    using (PowerShell shell = PowerShell.Create())
                    {
                        shell.Runspace = runspace;
                        // Process policy only, matching the old script launcher.
                        shell.AddCommand("Set-ExecutionPolicy").AddParameter("Scope", "Process")
                             .AddParameter("ExecutionPolicy", "Bypass").AddParameter("Force").Invoke();
                        shell.Commands.Clear();
                        shell.Streams.Error.Clear();
                        shell.AddCommand(Path.Combine(root, "server-panel.ps1")).Invoke();
                        if (shell.HadErrors)
                        {
                            string message = String.Join(Environment.NewLine, shell.Streams.Error);
                            File.WriteAllText(Path.Combine(root, "panel-error.log"), message);
                            MessageBox.Show(message, "Linux / WSL", MessageBoxButtons.OK, MessageBoxIcon.Error);
                            return 1;
                        }
                    }
                }
                return 0;
            }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(root, "panel-error.log"), error.ToString());
                MessageBox.Show(error.Message, "Linux / WSL", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
}
