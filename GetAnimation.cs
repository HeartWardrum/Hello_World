//放在Assets/Editor文件夹下
//选中fbx组件 点击unity界面顶端的AnimatorTool使用
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using System.IO;

public class GetAnimation
{
    [MenuItem("AnimationTool/GetAnimation", true)]
    static bool NotSelection()
    {
        return Selection.activeObject;     //判断是否选择的物体 没选择的话无法执行工具
    }

    [MenuItem("AnimationTool/GetAnimation")]
    static void Get()
    {
        string targetPath = Application.dataPath + "/AnimationClip";          //目录AnimationClip
        if (!Directory.Exists(targetPath))
        {
            Directory.CreateDirectory(targetPath);     //如果目录不存在就创建一个
        }
        UnityEngine.Object[] objects = Selection.GetFiltered(typeof(UnityEngine.Object), SelectionMode.Unfiltered);     //获取所有选中的物体
        foreach (UnityEngine.Object o in objects)     //遍历选择的物体
        {
            AnimationClip clip = new AnimationClip();      //new一个AnimationClip存放生成的AnimationClip
            string fbxPath = AssetDatabase.GetAssetPath(o);       //FBX的地址
            string name = o.name;     //FBX的名字
            AnimationClip fbxClip = AssetDatabase.LoadAssetAtPath<AnimationClip>(fbxPath);     //获取FBX上的animationClip
            if (fbxClip == null)
            {
                Debug.Log("当前选择的文件不是带有AnimationClip的FBX文件");
            }
            else
            {
                EditorUtility.CopySerialized(fbxClip, clip);    //复制
                AssetDatabase.CreateAsset(clip, "Assets/AnimationClip/" + name + ".anim");    //生成文件
            }
        }
    }
}