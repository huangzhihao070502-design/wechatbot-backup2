package com.backup.wechatbot;

import android.os.Bundle;
import android.widget.TextView;
import android.widget.ScrollView;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends AppCompatActivity {
    private TextView outputText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        outputText = findViewById(R.id.outputText);
        ScrollView scrollView = findViewById(R.id.scrollView);

        // 初始化 Python
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        Python py = Python.getInstance();

        // 在后台线程运行 Python
        new Thread(() -> {
            try {
                String result;
                try {
                    // 尝试调用 main 函数
                    py.getModule("ZynWechatBot_decrypted").callAttr("main");
                    result = "Python 执行完成";
                } catch (Exception e) {
                    // 如果没有 main 函数，直接 import 模块
                    py.getModule("ZynWechatBot_decrypted");
                    result = "Python 模块已加载: ZynWechatBot_decrypted.py";
                }

                String finalResult = result;
                runOnUiThread(() -> {
                    outputText.setText(finalResult);
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    outputText.setText("错误: " + e.getMessage());
                });
            }
        }).start();
    }
}
