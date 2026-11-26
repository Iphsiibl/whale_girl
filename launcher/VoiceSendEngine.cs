using System;
using System.Collections.Generic;
using System.Linq;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Automation;
using NAudio.CoreAudioApi;
using NAudio.Wave;
namespace WhaleLauncher;
public static class VoiceSendEngine
{
 public static Uri Endpoint(string address) {
  if(!Uri.TryCreate(address,UriKind.Absolute,out var u)||u.UserInfo.Length>0||!(u.Scheme=="https"||(u.Scheme=="http"&&u.IsLoopback))) throw new ArgumentException("请输入完整 HTTPS 合成地址，本地接口允许 HTTP"); return u;
 }
 public static double ValidateWave(string file) {
  using var w=new WaveFileReader(file);var n=w.TotalTime.TotalSeconds;
  if(!double.IsFinite(n)||w.Length<=0)throw new InvalidDataException("合成接口返回了空音频或异常音频");
  if(n<1)throw new ArgumentException($"合成音频实际只有 {n:F2} 秒，需达到 1 秒才能发送");
  if(n>55)throw new ArgumentException($"合成音频实际为 {n:F2} 秒，超过 55 秒发送上限，请缩短回复");
  return n;
 }
 public static async Task Generate(string address,string key,string model,string voice,string text,string file,CancellationToken ct) {
  using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct);deadline.CancelAfter(TimeSpan.FromSeconds(90));ct=deadline.Token;
  if(string.IsNullOrWhiteSpace(text)||text.Length>1000)throw new ArgumentException("请输入 1～1000 字");
  if(string.IsNullOrWhiteSpace(model)||string.IsNullOrWhiteSpace(voice))throw new ArgumentException("模型和音色 ID 不能为空");
  using var h=new HttpClient(new HttpClientHandler{AllowAutoRedirect=false}){Timeout=TimeSpan.FromSeconds(90)};
  using var q=new HttpRequestMessage(HttpMethod.Post,Endpoint(address)); if(!string.IsNullOrWhiteSpace(key))q.Headers.Authorization=new AuthenticationHeaderValue("Bearer",key.Trim());
  q.Content=new StringContent(JsonSerializer.Serialize(new{model,voice,input=text,response_format="wav"}),Encoding.UTF8,"application/json");
  using var r=await h.SendAsync(q,HttpCompletionOption.ResponseHeadersRead,ct); if(!r.IsSuccessStatusCode)throw new Exception("合成接口 HTTP "+(int)r.StatusCode+"，请检查独立 Key、地址和模型");
  using var s=await r.Content.ReadAsStreamAsync(ct);
  using(var f=new FileStream(file,FileMode.CreateNew,FileAccess.Write)){var b=new byte[16384]; long size=0; int n; while((n=await s.ReadAsync(b,ct))>0){size+=n;if(size>16*1024*1024)throw new Exception("音频超过 16 MB");await f.WriteAsync(b.AsMemory(0,n),ct);}}
  ValidateWave(file);
 }
 public sealed record Target(IntPtr Hwnd,string Chat);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll")] static extern short GetAsyncKeyState(int k);
 [DllImport("user32.dll")] static extern uint SendInput(uint n,INPUT[] input,int size);
 [DllImport("user32.dll")] static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint flags,uint timeout,out IntPtr result);
 [StructLayout(LayoutKind.Sequential)] struct INPUT {public uint type;public UNION data;}
 [StructLayout(LayoutKind.Explicit)] struct UNION {[FieldOffset(0)]public KEY key;[FieldOffset(0)]public MOUSE mouse;}
 [StructLayout(LayoutKind.Sequential)] struct KEY {public ushort vk,scan;public uint flags,time;public UIntPtr extra;}
 [StructLayout(LayoutKind.Sequential)] struct MOUSE {public int x,y;public uint data,flags,time;public UIntPtr extra;}
 static void Key(ushort k,bool up){var a=new[]{new INPUT{type=1,data=new UNION{key=new KEY{vk=k,flags=up?2u:0u}}}};if(SendInput(1,a,Marshal.SizeOf<INPUT>())!=1)throw new Exception("录音按键操作失败，请检查程序权限");}
 public static bool IsWeChatForeground(){try{GetWindowThreadProcessId(GetForegroundWindow(),out var pid);using var p=Process.GetProcessById((int)pid);return p.ProcessName.Equals("Weixin",StringComparison.OrdinalIgnoreCase)||p.ProcessName.Equals("WeChat",StringComparison.OrdinalIgnoreCase);}catch{return false;}}
 public static string CleanChatName(string name)=>System.Text.RegularExpressions.Regex.Replace((name??"").Trim(),@"(?:(?:长按|按住)鼠标\s*)?语音输入(?:文字)?$","").Trim();
 static string Chat(IntPtr h){var input=AutomationElement.FromHandle(h).FindFirst(TreeScope.Descendants,new PropertyCondition(AutomationElement.AutomationIdProperty,"chat_input_field"));if(input==null||string.IsNullOrWhiteSpace(input.Current.Name))throw new Exception("无法确认当前微信会话");return CleanChatName(input.Current.Name);}
 public static Target Capture(string recordingHotkey="Ctrl+Alt")
 {
  var shortcut=RecordingShortcut.Parse(recordingHotkey);
  if(!IsWeChatForeground())throw new Exception("请保持微信目标聊天在前台");
  var h=GetForegroundWindow();var chat=Chat(h);bool found=false;
  foreach(AutomationElement b in AutomationElement.FromHandle(h).FindAll(TreeScope.Descendants,new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Button)))
   if(shortcut.MatchesButton(b.Current.Name))found=true;
  if(!found)throw new Exception("微信的发语音快捷键与配置不一致，请在两边设置为 "+shortcut.Label);
  return new Target(h,chat);
 }
 static void Check(Target t,bool strict=true){
  // strict=false：后台录音模式。用户切到别的程序时不再中止录音 ——
  // 只要会话没变就继续录，这样鲸鲸说话时你还能接着干自己的事。
  // 会话真的变了（用户自己在微信里切了聊天）仍然中止。
  if(strict){if(GetForegroundWindow()!=t.Hwnd)throw new Exception("窗口或会话已变化，取消本次录音");}
  try{if(Chat(t.Hwnd)!=t.Chat)throw new Exception("窗口或会话已变化，取消本次录音");}
  catch(Exception e)when(!strict&&e.Message.Contains("无法确认当前微信会话")){/* 后台读不到控件树时不打断录音 */}
 }
 // 把「按键抬起」直接补发给微信：录音期间用户切走了，SendInput 的 key-up
 // 就送到了别的程序，微信那边按键还按着 → 录音停不下来、也发不出去。
 static void KeyUpTo(IntPtr hwnd,ushort vk){
  uint scan=0,extended=0;
  if(vk==0x11){scan=0x1D;extended=1;}
  else if(vk==0x12){scan=0x38;extended=1;}
  var lp=(IntPtr)(1|(scan<<16)|(extended<<24)|(1u<<30)|(1u<<29));
  SendMessageTimeout(hwnd,0x101,(IntPtr)vk,lp,2,300,out _);
 }
 public static async Task Play(string file,string deviceId,Target target,CancellationToken ct,string recordingHotkey="Ctrl+Alt",bool keepWhenUnfocused=false){
  var shortcut=RecordingShortcut.Parse(recordingHotkey);var held=new List<ushort>();
  ValidateWave(file);using var e=new MMDeviceEnumerator();using var d=e.GetDevice(deviceId);if(d.State!=DeviceState.Active||d.DataFlow!=DataFlow.Render)throw new Exception("所选声卡不可用");
  using var reader=new AudioFileReader(file);using var output=new WasapiOut(d,AudioClientShareMode.Shared,true,100);output.Init(reader);Exception error=null;output.PlaybackStopped+=(_,a)=>error=a.Exception;
  bool holding=false,done=false;
  try{
   if(target!=null)
   {
    var until=DateTime.UtcNow.AddSeconds(5);
    while(shortcut.Keys.Any(k=>(GetAsyncKeyState(k)&0x8000)!=0))
    {ct.ThrowIfCancellationRequested();if(DateTime.UtcNow>until)throw new Exception("请松开录音快捷键");await Task.Delay(30,ct);}
    Check(target);ct.ThrowIfCancellationRequested();holding=true;
    foreach(var k in shortcut.Keys){ct.ThrowIfCancellationRequested();held.Add(k);Key(k,false);}
    await Task.Delay(500,ct);
   }
   var end=DateTime.UtcNow.AddSeconds(reader.TotalTime.TotalSeconds+10);output.Play();while(output.PlaybackState==PlaybackState.Playing){ct.ThrowIfCancellationRequested();if(DateTime.UtcNow>end)throw new Exception("音频设备播放超时");if(target!=null)Check(target,!keepWhenUnfocused);await Task.Delay(80,ct);}if(error!=null)throw new Exception("播放失败",error);await Task.Delay(350,ct);if(target!=null)Check(target,!keepWhenUnfocused);done=true;
  }finally
  {
   try{output.Stop();}
   finally
   {
    if(holding)
    {
     if(!done)SendMessageTimeout(target.Hwnd,0x100,(IntPtr)0x1B,IntPtr.Zero,2,300,out _);
     Exception releaseError=null;
     foreach(var k in held.AsEnumerable().Reverse()){try{Key(k,true);}catch(Exception ex){releaseError??=ex;}}
     // 录音期间焦点跑到别的程序上了：把「按键抬起」也补发给微信，
     // 否则微信那边还按着 Ctrl+Alt，录音停不下来、消息也发不出去。
     if(target!=null&&GetForegroundWindow()!=target.Hwnd)foreach(var k in held.AsEnumerable().Reverse())KeyUpTo(target.Hwnd,k);
     if(releaseError!=null)throw releaseError;
    }
   }
  }
 }
}
