"""
全自动点火中枢 - 专家数字孪生系统一键启动脚本

[核心节点]：项目的唯一总启动入口
自动化流程编排：
    1. ETL 炼丹（数据清洗 → 知识提取 → 向量入库）
    2. 检查专家数据生成
    3. 启动后端网关（API Gateway）
    4. 启动前端界面（Streamlit）
    5. 自动打开浏览器

使用方法：
    python start_system.py
"""

import subprocess
import sys
import time
import os
import webbrowser
from pathlib import Path

# [核心节点]：Windows 编码对齐 - 强制 UTF-8 环境
os.environ["PYTHONIOENCODING"] = "utf-8"

# [核心节点]：创建 UTF-8 环境变量副本，用于传递给所有子进程
ENV_UTF8 = os.environ.copy()
ENV_UTF8["PYTHONIOENCODING"] = "utf-8"


def cleanup_logs():
    """
    [核心节点]：启动前清理日志文件
    确保每次启动都有干净的日志环境
    """
    log_file = Path("logs/error_log.txt")
    if log_file.exists():
        try:
            log_file.unlink()
            print("[清理] 已重置错误日志")
        except Exception as e:
            print(f"[!] 清理日志失败: {e}")


def print_banner():
    """打印启动横幅"""
    print("=" * 80)
    print("🔥 专家数字孪生系统 - 全自动点火中枢")
    print("=" * 80)
    print("[系统点火中] 正在启动全自动部署流程...")
    print("=" * 80)


def run_ingestion_phase():
    """
    [核心节点]：步骤 1 - 数据探针清洗阶段（低成本，可随意运行）
    调用通用接入智能体进行数据结构嗅探和归一化
    绝不自动执行 ETL（灵魂蒸馏）阶段以节省 Token
    """
    print("\n[步骤 1/3] 🔍 数据探针清洗 - Ingestion Phase")
    print("-" * 80)
    
    # [核心节点]：检查源数据文件是否存在
    source_file = Path("data/raw/source_data.csv")
    if not source_file.exists():
        print(f"[!] 源数据文件不存在: {source_file}")
        print("[提示] 请将脏数据文件放置在 data/raw/ 目录下")
        print("[提示] 支持的文件格式: .csv, .jsonl, .xlsx")
        print("[示例] 将 source_data.csv 放入 data/raw/ 目录")
        return False
    
    print(f"[✓] 找到源数据文件: {source_file}")
    print("[探针清洗] 调用通用接入智能体嗅探数据结构...")
    print("-" * 80)
    
    try:
        # [核心节点]：只执行通用接入智能体（低成本），绝不自动执行 ETL（高成本）
        result = subprocess.run(
            [sys.executable, "-c", 
             "from tools.universal_ingestor import main; main()" if Path("tools/universal_ingestor.py").exists() 
             else "from tools.local_corpus_parser import main; main()"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=ENV_UTF8,
            cwd=str(Path(__file__).parent)
        )
        
        if result.stdout:
            print(result.stdout)
        
        if result.returncode != 0:
            print(f"[!] 数据清洗阶段异常: {result.returncode}")
            if result.stderr:
                print(f"[!] 错误: {result.stderr[:500]}")
            return False
        
        # [核心节点]：检查暂存区数据是否生成（从 .env 读取 LATEST_STAGING_FILE）
        from dotenv import load_dotenv
        load_dotenv()
        latest_staging = os.getenv("LATEST_STAGING_FILE")
        
        if latest_staging and Path(latest_staging).exists():
            staging_file = Path(latest_staging)
            line_count = sum(1 for _ in staging_file.open(encoding='utf-8'))
            print(f"[✓] 暂存区数据已生成: {staging_file} ({line_count} 条记录)")
            return True
        else:
            print(f"[!] 暂存区数据未生成或 .env 未更新")
            print(f"[!] 请检查 LATEST_STAGING_FILE: {latest_staging}")
            return False
        
    except Exception as e:
        print(f"[!] 数据清洗阶段失败: {type(e).__name__}: {e}")
        return False


def prompt_etl_confirmation():
    """
    [核心节点]：防破产机制 - ETL 阶段必须由指挥官手动确认
    打印提示信息，要求手动运行 ETL 流程
    """
    print("\n" + "=" * 80)
    print("⚠️  【防破产机制】ETL 阶段（灵魂蒸馏）需要手动触发")
    print("=" * 80)
    print("\n[阶段说明]")
    print("  • 探针清洗 (Ingestion): 已完成 ✓")
    print("  • 灵魂蒸馏 (ETL): 需要手动确认 ⚠️")
    print("\n[Token 成本警告]")
    print("  • ETL 阶段将调用大模型进行：")
    print("    - Map 阶段知识提取（按 Chunk 计费）")
    print("    - Reduce 阶段知识审查（按 Chunk 计费）")
    print("    - 数字孪生侧写（单次高消耗）")
    print("\n[操作指令]")
    print("  请指挥官手动确认 staging_corpus.jsonl 数据无误后，再执行：")
    print("\n  >>> python services/etl_pipeline.py")
    print("\n" + "=" * 80)
    return False


def check_expert_data():
    """
    [核心节点]：检查专家数据是否已生成
    扫描 data/experts/ 目录确认专家克隆成功
    """
    print("\n[检查点] 🔍 验证专家数据生成状态")
    print("-" * 80)
    
    experts_dir = Path("data/experts")
    
    if not experts_dir.exists():
        print(f"[!] 专家数据目录不存在: {experts_dir}")
        print("[提示] 首次启动，正在执行专家画像冷启动...")
        print("[提示] 请确保 source_data.csv 已放入项目根目录")
        return False
    
    # 扫描专家目录
    expert_folders = [d for d in experts_dir.iterdir() if d.is_dir()]
    
    if not expert_folders:
        print("[!] 未找到任何专家数据")
        print("[提示] 首次启动，正在执行专家画像冷启动...")
        print("[提示] ETL 流程将自动创建专家档案")
    
    if not expert_folders:
        print(f"[!] 未找到任何专家数据")
        print("[!] ETL 流程可能未完成或 source_data.csv 格式有误")
        return False
    
    print(f"[✓] 检测到 {len(expert_folders)} 个专家档案:")
    for expert_dir in expert_folders:
        profile_file = expert_dir / "profile.json"
        knowledge_file = expert_dir / "knowledge.json"
        
        has_profile = profile_file.exists()
        has_knowledge = knowledge_file.exists()
        
        status = "✓" if (has_profile and has_knowledge) else "⚠"
        print(f"    {status} {expert_dir.name}/")
        print(f"       - 画像: {'✓' if has_profile else '✗'} profile.json")
        print(f"       - 知识: {'✓' if has_knowledge else '✗'} knowledge.json")
    
    return True


def start_backend():
    """
    [核心节点]：步骤 2 - 启动后端 FastAPI 网关
    """
    print("\n[步骤 2/4] 🚀 启动后端网关")
    print("-" * 80)
    
    try:
        # 使用 subprocess.Popen 非阻塞启动
        # [核心节点]：显式声明编码和环境变量防止 Windows 编码冲突
        backend_process = subprocess.Popen(
            [sys.executable, "api_gateway.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=ENV_UTF8
        )
        
        print(f"[✓] 后端网关启动中 (PID: {backend_process.pid})")
        return backend_process
        
    except Exception as e:
        print(f"[!] 后端网关启动失败: {type(e).__name__}: {e}")
        return None


def start_frontend():
    """
    [核心节点]：步骤 3 - 启动前端 Streamlit 界面
    """
    print("\n[步骤 3/4] 🌐 启动前端界面")
    print("-" * 80)
    
    try:
        # 使用 subprocess.Popen 非阻塞启动
        # [核心节点]：显式声明编码和环境变量防止 Windows 编码冲突
        frontend_process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "web_ui.py", "--server.port", "8501"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=ENV_UTF8
        )
        
        print(f"[✓] 前端界面启动中 (PID: {frontend_process.pid})")
        return frontend_process
        
    except Exception as e:
        print(f"[!] 前端界面启动失败: {type(e).__name__}: {e}")
        return None


def open_browser():
    """
    [核心节点]：步骤 4 - 自动打开浏览器
    """
    print("\n[步骤 4/4] 🌍 自动打开浏览器")
    print("-" * 80)
    
    frontend_url = "http://localhost:8501"
    
    try:
        print(f"[正在打开] {frontend_url}")
        webbrowser.open(frontend_url, new=2)  # new=2 表示在新标签页打开
        print(f"[✓] 浏览器已自动打开")
        return True
        
    except Exception as e:
        print(f"[!] 浏览器自动打开失败: {e}")
        print(f"[!] 请手动访问: {frontend_url}")
        return False


def shutdown_services(backend_process, frontend_process):
    """优雅关闭所有服务"""
    print("\n[!] 正在关闭所有服务...")
    print("-" * 80)
    
    try:
        if backend_process and backend_process.poll() is None:
            backend_process.terminate()
            print(f"[✓] 后端网关已关闭 (PID: {backend_process.pid})")
    except Exception as e:
        print(f"[!] 关闭后端时出错: {e}")
    
    try:
        if frontend_process and frontend_process.poll() is None:
            frontend_process.terminate()
            print(f"[✓] 前端界面已关闭 (PID: {frontend_process.pid})")
    except Exception as e:
        print(f"[!] 关闭前端时出错: {e}")
    
    print("=" * 80)
    print("[✓] 所有服务已安全关闭")
    print("=" * 80)


if __name__ == "__main__":
    # [核心节点]：启动前清理
    cleanup_logs()
    
    print_banner()
    
    backend_process = None
    frontend_process = None
    
    try:
        # [核心节点]：步骤 1 - 数据探针清洗（低成本阶段）
        # 绝不自动执行 ETL（高成本），必须由指挥官手动确认
        ingestion_success = run_ingestion_phase()
        
        if not ingestion_success:
            print("\n[!] 数据探针清洗失败，无法继续")
            print("[!] 请检查 source_data.csv 是否存在且格式正确")
            sys.exit(1)
        
        # [核心节点]：防破产机制 - ETL 阶段需要手动触发
        # ETL 烧钱（Token），必须由指挥官手动确认数据无误后再执行
        prompt_etl_confirmation()
        
        # [核心节点]：检查专家数据是否已生成（之前手动运行 ETL 的结果）
        expert_ready = check_expert_data()
        
        if not expert_ready:
            print("\n[!] 专家数据未就绪（请先手动执行 ETL 流程）")
            print("[!] 执行指令: python services/etl_pipeline.py")
            # 继续启动服务，但提醒用户专家功能可能不可用
        
        # 步骤 2: 启动后端
        backend_process = start_backend()
        
        if backend_process is None:
            print("\n[!] 后端网关启动失败，终止启动流程")
            sys.exit(1)
        
        # 等待后端就绪（3秒）
        print(f"\n[等待] ⏱️  等待后端网关就绪 (3秒)...")
        time.sleep(3)
        print("[✓] 网关已就绪，端口 8088")
        
        # 步骤 3: 启动前端
        frontend_process = start_frontend()
        
        if frontend_process is None:
            print("\n[!] 前端界面启动失败")
            shutdown_services(backend_process, None)
            sys.exit(1)
        
        # 等待前端就绪（5秒）
        print(f"\n[等待] ⏱️  等待前端界面就绪 (5秒)...")
        time.sleep(5)
        print("[✓] 前端已就绪，端口 8501")
        
        # 步骤 4: 打开浏览器
        open_browser()
        
        # 启动完成横幅
        print("\n" + "=" * 80)
        print("🎉 全自动点火完成！专家数字孪生系统已就绪")
        print("=" * 80)
        print("[服务状态]")
        print(f"  ✓ 后端网关: http://localhost:8088 (PID: {backend_process.pid})")
        print(f"  ✓ 前端界面: http://localhost:8501 (PID: {frontend_process.pid})")
        print("[操作指南]")
        print("  • 在浏览器中开始对话")
        print("  • 侧边栏'专家档案室'可切换不同专家")
        print("  • 按 Ctrl+C 关闭所有服务")
        print("=" * 80)
        
        # 保持运行，等待中断信号
        try:
            while True:
                # 检查进程是否还在运行
                backend_status = backend_process.poll()
                frontend_status = frontend_process.poll()
                
                if backend_status is not None:
                    print(f"\n[!] 后端网关异常退出 (code: {backend_status})")
                    break
                    
                if frontend_status is not None:
                    print(f"\n[!] 前端界面异常退出 (code: {frontend_status})")
                    break
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\n[!] 收到中断信号 (Ctrl+C)")
        
    except Exception as e:
        print(f"\n[!] 系统启动异常: {type(e).__name__}: {e}")
        
    finally:
        # 优雅关闭所有服务
        shutdown_services(backend_process, frontend_process)

