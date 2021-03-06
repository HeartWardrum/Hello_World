//直接丢进工程文件夹中就能使用
using System.IO;

namespace UGUIFrameWorkEditor
{
    public class ChinarScriptFirstComment : UnityEditor.AssetModificationProcessor
    {
        /// <summary>
        /// 在资源创建时调用
        /// </summary>
        /// <param name="path">自动传入资源路径</param>
        public static void OnWillCreateAsset(string path)
        {
            path = path.Replace(".meta", "");
            if (!path.EndsWith(".cs")) return;
            string allText = "// ========================================================\r\n"
                             + "// 作者：HeartWardrum \r\n"
                             + "// 邮箱：1208195222@qq.com \r\n"
                             + "// 创建时间：#CreateTime#\r\n"
                             + "// 描述：\r\n"
                             + "// ========================================================\r\n";
            allText += File.ReadAllText(path);
            allText = allText.Replace("#CreateTime#", System.DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
            File.WriteAllText(path, allText);
        }
    }
}