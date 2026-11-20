use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Mutex};
use std::time::Duration;
use tauri::{Manager, RunEvent};

#[derive(Clone, Serialize)]
pub struct BackendConfig {
    pub url: String,
    pub token: String,
}

#[derive(Deserialize)]
struct HandshakePayload {
    ready: bool,
    url: String,
    token: String,
}

struct BackendHandle {
    config: BackendConfig,
    child: Mutex<Option<Child>>,
    #[cfg(windows)]
    job_handle: Mutex<usize>,
}

impl BackendHandle {
    fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut proc_child) = guard.take() {
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;
                    let _ = Command::new("taskkill")
                        .args(["/F", "/T", "/PID", &proc_child.id().to_string()])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output();
                }
                let _ = proc_child.kill();
                let _ = proc_child.wait();
            }
        }
        #[cfg(windows)]
        if let Ok(mut jg) = self.job_handle.lock() {
            let raw = *jg;
            *jg = 0;
            if raw != 0 {
                unsafe {
                    windows_sys::Win32::Foundation::CloseHandle(raw as windows_sys::Win32::Foundation::HANDLE);
                }
            }
        }
    }
}

fn find_repo_root(start: &Path) -> Option<PathBuf> {
    let mut cur = Some(start.to_path_buf());
    while let Some(dir) = cur {
        if dir.join(".venv").join("Scripts").join("python.exe").is_file()
            && dir.join("gis_agent").is_dir()
        {
            return Some(dir);
        }
        cur = dir.parent().map(Path::to_path_buf);
    }
    None
}

fn resolve_python_executable() -> Result<(PathBuf, Option<PathBuf>, PathBuf), String> {
    let exe_path = std::env::current_exe().map_err(|e| format!("无法获取程序路径: {e}"))?;
    let exe_dir = exe_path
        .parent()
        .ok_or_else(|| "无法定位程序安装目录".to_string())?;

    let bundled = [
        exe_dir.join("runtime").join("python.exe"),
        exe_dir.join("resources").join("runtime").join("python.exe"),
    ];
    for py in bundled {
        if py.is_file() {
            let proj = std::env::current_dir().unwrap_or_else(|_| exe_dir.to_path_buf());
            return Ok((py, None, proj));
        }
    }

    if let Ok(env_py) = std::env::var("OPENGIS_PYTHON") {
        let p = PathBuf::from(env_py.trim());
        if p.is_file() {
            let repo = find_repo_root(exe_dir).or_else(|| std::env::current_dir().ok().and_then(|d| find_repo_root(&d)));
            let proj = repo.clone().unwrap_or_else(|| exe_dir.to_path_buf());
            return Ok((p, repo, proj));
        }
    }

    if let Some(repo) = find_repo_root(exe_dir)
        .or_else(|| std::env::current_dir().ok().and_then(|d| find_repo_root(&d)))
    {
        return Ok((
            repo.join(".venv").join("Scripts").join("python.exe"),
            Some(repo.clone()),
            repo,
        ));
    }

    Err("未找到随包 Python 运行时 (runtime/python.exe) 或开发环境 .venv。".to_string())
}

#[cfg(windows)]
fn attach_kill_on_close_job(child: &Child) -> usize {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return 0;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const std::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            CloseHandle(job);
            return 0;
        }
        let assigned = AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE);
        if assigned == 0 {
            CloseHandle(job);
            return 0;
        }
        job as usize
    }
}

fn spawn_backend() -> Result<BackendHandle, String> {
    let (python_exe, repo_root, project_dir) = resolve_python_executable()?;
    let mut cmd = Command::new(&python_exe);
    cmd.args([
        "-s",
        "-m",
        "gis_agent.server.app",
        "--port",
        "0",
        "--parent-pid",
        &std::process::id().to_string(),
        "--project",
        &project_dir.to_string_lossy(),
    ]);
    cmd.env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONNOUSERSITE", "1")
        .env_remove("PYTHONPATH")
        .env_remove("PROJ_LIB")
        .env_remove("PROJ_DATA")
        .env_remove("GDAL_DATA")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    if let Some(root) = &repo_root {
        let mut py_path = root.to_string_lossy().to_string();
        if let Ok(prev) = std::env::var("PYTHONPATH") {
            if !prev.is_empty() {
                py_path.push(';');
                py_path.push_str(&prev);
            }
        }
        cmd.env("PYTHONPATH", py_path);
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("无法启动本地空间引擎服务 ({}): {e}", python_exe.display()))?;

    #[cfg(windows)]
    let job_handle = attach_kill_on_close_job(&child);

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "无法读取后端就绪输出".to_string())?;
    let (tx, rx) = mpsc::channel::<Result<HandshakePayload, String>>();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    let trimmed = text.trim();
                    if trimmed.starts_with('{') {
                        if let Ok(hs) = serde_json::from_str::<HandshakePayload>(trimmed) {
                            if hs.ready {
                                let _ = tx.send(Ok(hs));
                                return;
                            }
                        }
                    }
                }
                Err(e) => {
                    let _ = tx.send(Err(format!("读取后端输出失败: {e}")));
                    return;
                }
            }
        }
        let _ = tx.send(Err("本地空间引擎服务在就绪前意外退出".to_string()));
    });

    let hs = rx
        .recv_timeout(Duration::from_secs(20))
        .map_err(|_| "等待本地空间引擎启动超时 (20s)".to_string())??;

    Ok(BackendHandle {
        config: BackendConfig {
            url: hs.url,
            token: hs.token,
        },
        child: Mutex::new(Some(child)),
        #[cfg(windows)]
        job_handle: Mutex::new(job_handle),
    })
}

#[tauri::command]
fn get_backend_config(state: tauri::State<'_, BackendHandle>) -> BackendConfig {
    state.config.clone()
}

#[tauri::command]
fn open_path_external(path: String, action: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err(format!("路径不存在: {}", target.display()));
    }
    #[cfg(windows)]
    {
        if action == "reveal" {
            Command::new("explorer")
                .arg(format!("/select,{}", target.display()))
                .spawn()
                .map_err(|e| e.to_string())?;
        } else {
            Command::new("cmd")
                .args(["/C", "start", "", &target.to_string_lossy()])
                .spawn()
                .map_err(|e| e.to_string())?;
        }
    }
    #[cfg(target_os = "macos")]
    {
        let args: Vec<&str> = if action == "reveal" { vec!["-R"] } else { vec![] };
        Command::new("open")
            .args(args)
            .arg(&target)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let p = if action == "reveal" && target.is_file() {
            target.parent().unwrap_or(&target)
        } else {
            target.as_path()
        };
        Command::new("xdg-open").arg(p).spawn().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = spawn_backend().expect("Failed to start OpenGIS Studio backend");
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(backend)
        .invoke_handler(tauri::generate_handler![get_backend_config, open_path_external])
        .build(tauri::generate_context!())
        .expect("error while building OpenGIS Studio");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            app_handle.state::<BackendHandle>().shutdown();
        }
    });
}
