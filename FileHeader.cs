using System.IO;

namespace UGUIFrameWorkEditor
{
    public class ChinarScriptFirstComment : UnityEditor.AssetModificationProcessor
    {
        /// <summary>
        /// ����Դ����ʱ����
        /// </summary>
        /// <param name="path">�Զ�������Դ·��</param>
        public static void OnWillCreateAsset(string path)
        {
            path = path.Replace(".meta", "");
            if (!path.EndsWith(".cs")) return;
            string allText = "// ========================================================\r\n"
                             + "// ���ߣ�HeartWardrum \r\n"
                             + "// ���䣺1208195222@qq.com \r\n"
                             + "// ����ʱ�䣺#CreateTime#\r\n"
                             + "// ������\r\n"
                             + "// ========================================================\r\n";
            allText += File.ReadAllText(path);
            allText = allText.Replace("#CreateTime#", System.DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
            File.WriteAllText(path, allText);
        }
    }
}